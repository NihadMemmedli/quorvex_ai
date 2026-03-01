#!/usr/bin/env python3
"""
Quorvex AI CLI
Entry point for natural language test generation.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_command(
    command: str, stream_output: bool = False, interactive: bool = False, is_python: bool = True, env: dict = None
) -> subprocess.CompletedProcess:
    """
    Run a shell command using the current python executable.

    Args:
        command: The command string
        stream_output: Whether to print stdout in real-time
        interactive: Whether to attach stdin/stdout for user interaction
        is_python: Whether to prefix with python executable (default: True)
        env: Optional environment variables to pass

    Returns:
        CompletedProcess object
    """
    # Use the same python interpreter that launch this CLI
    if is_python:
        python_exe = sys.executable
        full_cmd = f'"{python_exe}" {command}'
    else:
        full_cmd = command

    if interactive:
        # Run interactively, inheriting stdio
        return subprocess.run(full_cmd, shell=True, env=env)

    if stream_output:
        process = subprocess.Popen(
            full_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, env=env
        )

        stdout_lines = []
        while True:
            output = process.stdout.readline()
            if output == "" and process.poll() is not None:
                break
            if output:
                print(output.strip())
                stdout_lines.append(output)
                sys.stdout.flush()

        stderr = process.stderr.read()
        return_code = process.poll()

        result = subprocess.CompletedProcess(args=full_cmd, returncode=return_code)
        result.stdout = "".join(stdout_lines)
        result.stderr = stderr
        return result
    else:
        return subprocess.run(full_cmd, shell=True, capture_output=True, text=True, env=env)


def print_output(result: subprocess.CompletedProcess):
    """Print stdout and safe stderr from process result."""
    if result.stderr and "cancel scope" not in result.stderr:
        print(f"STDERR: {result.stderr}", file=sys.stderr)


def _show_memory_stats(project_id: str = None):
    """Display memory system statistics."""
    print("=" * 60)
    print("📊 MEMORY SYSTEM STATUS")
    print("=" * 60)
    print()

    try:
        # Add orchestrator path for imports and load environment
        sys.path.insert(0, str(Path(__file__).parent))

        # Load environment variables from .env file
        from orchestrator.load_env import setup_claude_env

        setup_claude_env()

        from orchestrator.memory import get_memory_manager
        from orchestrator.memory.config import get_config
        from orchestrator.memory.vector_store import _get_chroma_client

        # Get config
        config = get_config()
        effective_project = project_id or config.project_id or "default"

        print(f"Project ID: {effective_project}")
        print(f"Data Directory: {config.persist_directory}")
        print(f"Memory Enabled: {config.memory_enabled}")
        print()

        # Initialize memory manager
        manager = get_memory_manager(project_id=effective_project)

        # --- Vector Store Stats ---
        print("📦 Vector Store (ChromaDB)")
        print("-" * 40)

        # Get patterns
        patterns = manager.vector_store.get_all_patterns()
        pattern_count = len(patterns)

        # Calculate success rate if patterns exist
        if pattern_count > 0:
            success_rates = [p["metadata"].get("success_rate", 0) for p in patterns if p.get("metadata")]
            avg_success_rate = sum(success_rates) / len(success_rates) if success_rates else 0
            print(f"  Patterns: {pattern_count} (avg success rate: {avg_success_rate:.0%})")

            # Count actions
            actions = {}
            for p in patterns:
                action = p.get("metadata", {}).get("action", "unknown")
                actions[action] = actions.get(action, 0) + 1

            # Top 5 actions
            sorted_actions = sorted(actions.items(), key=lambda x: x[1], reverse=True)[:5]
            if sorted_actions:
                action_str = ", ".join([f"{a} ({c})" for a, c in sorted_actions])
                print(f"  Top actions: {action_str}")
        else:
            print("  Patterns: 0")

        # List all collections in ChromaDB
        try:
            client = _get_chroma_client(config.persist_directory)
            collections = client.list_collections()
            if collections:
                print(f"  Collections: {len(collections)}")
                for coll in collections:
                    count = coll.count()
                    print(f"    - {coll.name}: {count} items")
        except Exception as e:
            print(f"  Collections: Error - {e}")

        print()

        # --- Graph Store Stats ---
        print("🔗 Graph Store (NetworkX)")
        print("-" * 40)

        try:
            graph_stats = manager.graph_store.get_graph_stats()
            print(f"  Pages: {graph_stats.get('page_count', 0)}")
            print(f"  Elements: {graph_stats.get('element_count', 0)}")
            print(f"  Flows: {graph_stats.get('flow_count', 0)}")
            print(f"  Tested Elements: {graph_stats.get('tested_elements', 0)}")
            print(f"  Element Coverage: {graph_stats.get('element_coverage', 0):.1f}%")

            # Show flows if any
            flows = manager.graph_store.get_all_flows()
            if flows:
                print("  Flow Names:")
                for flow in flows[:5]:
                    print(f"    - {flow.get('name', 'Unnamed')}")
                if len(flows) > 5:
                    print(f"    ... and {len(flows) - 5} more")
        except Exception as e:
            print(f"  Error loading graph: {e}")

        print()

        # --- Recent Patterns ---
        if pattern_count > 0:
            print("📝 Recent Patterns")
            print("-" * 40)
            # Sort by created_at if available
            sorted_patterns = sorted(patterns, key=lambda p: p.get("metadata", {}).get("created_at", ""), reverse=True)[
                :5
            ]
            for p in sorted_patterns:
                meta = p.get("metadata", {})
                action = meta.get("action", "?")
                target = meta.get("target", "?")[:30]
                success_rate = meta.get("success_rate", 0)
                test_name = meta.get("test_name", "unknown")[:25]
                print(f"  [{action}] {target} ({success_rate:.0%}) - {test_name}")

                # Show new fields if available
                playwright_selector = meta.get("playwright_selector", "")
                page_url = meta.get("page_url", "")
                strategy = meta.get("strategy", "")

                if playwright_selector:
                    # Truncate long selectors
                    selector_display = (
                        playwright_selector[:60] + "..." if len(playwright_selector) > 60 else playwright_selector
                    )
                    print(f"    Selector: {selector_display}")
                if page_url:
                    print(f"    Page: {page_url}")
                if strategy and strategy != "unknown":
                    # Build strategy details
                    strategy_info = f"Strategy: {strategy}"
                    if meta.get("element_role"):
                        strategy_info += f" | Role: {meta.get('element_role')}"
                    if meta.get("element_name"):
                        strategy_info += f" | Name: {meta.get('element_name')}"
                    if meta.get("element_label"):
                        strategy_info += f" | Label: {meta.get('element_label')}"
                    print(f"    {strategy_info}")

        print()
        print("=" * 60)

    except ImportError as e:
        print(f"❌ Memory system not available: {e}")
        print("   Make sure you're running from the project root.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error reading memory stats: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Convert natural language test specs to Playwright code.")
    parser.add_argument("spec", nargs="?", help="Path to the markdown specification file or PRD PDF (with --prd)")
    parser.add_argument(
        "--prd",
        action="store_true",
        help="Treat input file as a PDF PRD to be processed",
    )
    parser.add_argument(
        "--standard-pipeline",
        action="store_true",
        help="Use classic pipeline (Plan->Op->Exp) instead of native. Not recommended.",
    )
    parser.add_argument(
        "--pipeline",
        choices=["standard", "native"],
        default="native",
        help="[DEPRECATED] Use --standard-pipeline instead. Default is now native.",
    )
    parser.add_argument(
        "--feature",
        help="Specific feature to generate from PRD (Native Pipeline only)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Enable interactive mode (plan review and step confirmation)",
    )
    parser.add_argument(
        "--run-dir",
        help="Specific directory to store run artifacts",
    )

    parser.add_argument(
        "--try-code",
        help="Path to existing generated code to try before regenerating",
    )
    parser.add_argument(
        "--browser",
        default="chromium",
        choices=["chromium", "firefox", "webkit"],
        help="Browser project to run tests on (default: chromium)",
    )
    parser.add_argument(
        "--project-id", help="Project ID for memory system isolation (default: derived from spec folder)"
    )
    parser.add_argument("--no-memory", action="store_true", help="Disable memory system for this run")
    parser.add_argument(
        "--hybrid", action="store_true", help="Use hybrid healing (Native 3 attempts → Ralph up to 17 more)"
    )
    parser.add_argument(
        "--max-iterations", type=int, default=20, help="Maximum healing iterations (default: 20, used with --hybrid)"
    )
    parser.add_argument(
        "--split", action="store_true", help="Split PRD spec into individual test specs (one per test case)"
    )
    parser.add_argument("--split-output-dir", help="Output directory for split specs (default: <spec-name>-tests/)")
    parser.add_argument("--memory-stats", action="store_true", help="Show memory system statistics and exit")

    # === AI-POWERED EXPLORATION & RTM ===
    parser.add_argument("--explore", metavar="URL", help="Start AI-powered exploration of a web application")
    parser.add_argument("--exploration-results", metavar="SESSION_ID", help="View results from an exploration session")
    parser.add_argument(
        "--generate-requirements", action="store_true", help="Generate requirements from exploration data"
    )
    parser.add_argument(
        "--from-exploration", metavar="SESSION_ID", help="Exploration session ID to generate requirements from"
    )
    parser.add_argument("--generate-rtm", action="store_true", help="Generate Requirements Traceability Matrix")
    parser.add_argument("--rtm-export", choices=["markdown", "csv", "html"], help="Export RTM in specified format")
    parser.add_argument("--output", "-o", help="Output file path (for exports)")
    parser.add_argument(
        "--max-interactions", type=int, default=50, help="Maximum interactions for exploration (default: 50)"
    )
    parser.add_argument(
        "--strategy",
        choices=["goal_directed", "breadth_first", "depth_first"],
        default="goal_directed",
        help="Exploration strategy (default: goal_directed)",
    )
    parser.add_argument("--timeout", type=int, default=30, help="Exploration timeout in minutes (default: 30)")
    parser.add_argument("--login-url", help="Login URL for authenticated exploration")

    # === API TESTING ===
    parser.add_argument(
        "--api", action="store_true", help="Force API test generation mode (auto-detected from spec if not set)"
    )
    parser.add_argument(
        "--generate-api-tests",
        action="store_true",
        help="Generate API tests from exploration data (requires --from-exploration)",
    )
    parser.add_argument(
        "--api-tests", action="store_true", help="Generate API tests from an OpenAPI/Swagger spec file or URL"
    )
    parser.add_argument(
        "--generate-edge-cases", action="store_true", help="Auto-generate edge case and security tests for an API spec"
    )

    # === SKILL MODE ===
    parser.add_argument(
        "--skill-mode",
        action="store_true",
        help="Use skill-based execution for complex scenarios (network interception, multi-tab, etc.)",
    )
    parser.add_argument("--run-skill", metavar="SCRIPT", help="Execute a Playwright skill script directly")
    parser.add_argument(
        "--skill-timeout", type=int, default=30000, help="Skill script timeout in milliseconds (default: 30000)"
    )
    parser.add_argument(
        "--skill-headless", action="store_true", default=None, help="Run skill scripts in headless mode"
    )

    # Legacy flags (kept for backward compatibility but not advertised)
    parser.add_argument("--ralph", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--native-healer", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--native-generator", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # --- MEMORY STATS COMMAND ---
    if args.memory_stats:
        _show_memory_stats(args.project_id)
        sys.exit(0)

    # === SKILL EXECUTION COMMANDS ===

    # --- RUN SKILL DIRECTLY ---
    if args.run_skill:
        import asyncio

        from orchestrator.workflows.skill_executor import SkillExecutor

        print("=" * 80)
        print("🎭 SKILL EXECUTION MODE")
        print("=" * 80)
        print(f"   Script: {args.run_skill}")
        print(f"   Timeout: {args.skill_timeout}ms")
        headless = args.skill_headless if args.skill_headless is not None else True
        print(f"   Headless: {headless}")
        print()

        project_id = args.project_id or "default"
        executor = SkillExecutor(project_id=project_id)

        try:
            result = asyncio.run(
                executor.execute_script_file(
                    script_path=args.run_skill,
                    timeout_ms=args.skill_timeout,
                    headless=headless,
                )
            )

            print()
            print("=" * 80)
            if result.success:
                print("✅ Skill executed successfully")
                print(f"   Duration: {result.duration_ms}ms")
                if result.output:
                    print(f"   Output: {json.dumps(result.output, indent=2)}")
                if result.screenshots:
                    print(f"   Screenshots: {len(result.screenshots)}")
                    for ss in result.screenshots:
                        print(f"     - {ss}")
            else:
                print("❌ Skill execution failed")
                if result.error:
                    print(f"   Error: {result.error}")
            print("=" * 80)

            sys.exit(0 if result.success else 1)

        except KeyboardInterrupt:
            print("\nExecution stopped by user")
            sys.exit(1)
        except Exception as e:
            if "cancel scope" in str(e).lower():
                pass
            else:
                print(f"\n❌ Skill execution error: {e}")
                import traceback

                traceback.print_exc()
                sys.exit(1)

    # === AI-POWERED EXPLORATION COMMANDS ===

    # --- EXPLORATION COMMAND ---
    if args.explore:
        import asyncio

        from orchestrator.workflows.app_explorer import run_exploration

        print("=" * 80)
        print("🔍 AI-POWERED APP EXPLORATION")
        print("=" * 80)
        print(f"   URL: {args.explore}")
        print(f"   Strategy: {args.strategy}")
        print(f"   Max Interactions: {args.max_interactions}")
        print(f"   Timeout: {args.timeout} minutes")
        print()

        # Check for credentials in environment
        credentials = None
        if os.environ.get("LOGIN_USERNAME") or os.environ.get("LOGIN_EMAIL"):
            username_var = "LOGIN_EMAIL" if os.environ.get("LOGIN_EMAIL") else "LOGIN_USERNAME"
            password_var = "LOGIN_PASSWORD"
            credentials = {
                "username": os.environ.get(username_var, ""),
                "password": os.environ.get(password_var, ""),
                "username_var": username_var,
                "password_var": password_var,
            }
            print(f"   Authentication: Enabled (using {username_var})")

        project_id = args.project_id or "default"

        try:
            result = asyncio.run(
                run_exploration(
                    entry_url=args.explore,
                    project_id=project_id,
                    max_interactions=args.max_interactions,
                    strategy=args.strategy,
                    timeout_minutes=args.timeout,
                    credentials=credentials,
                    login_url=args.login_url,
                )
            )

            print()
            print("=" * 80)
            if result.status == "completed":
                print("✅ Exploration Complete!")
                print(f"   Session ID: {result.session_id}")
                print(f"   Pages: {result.pages_discovered}")
                print(f"   Flows: {len(result.flows)}")
                print(f"   API Endpoints: {len(result.api_endpoints)}")
                print()
                print("Next steps:")
                print(f"  python orchestrator/cli.py --generate-requirements --from-exploration {result.session_id}")
            else:
                print(f"⚠️ Exploration ended with status: {result.status}")
                if result.error_message:
                    print(f"   Error: {result.error_message}")
            print("=" * 80)

        except KeyboardInterrupt:
            print("\nExploration stopped by user")
        except Exception as e:
            if "cancel scope" in str(e).lower():
                pass  # Ignore SDK cleanup error
            else:
                print(f"\n❌ Exploration error: {e}")
                import traceback

                traceback.print_exc()

        sys.exit(0)

    # --- EXPLORATION RESULTS COMMAND ---
    if args.exploration_results:
        from orchestrator.memory.exploration_store import get_exploration_store

        session_id = args.exploration_results
        project_id = args.project_id or "default"
        store = get_exploration_store(project_id=project_id)

        session = store.get_session(session_id)
        if not session:
            print(f"❌ Session not found: {session_id}")
            sys.exit(1)

        print("=" * 80)
        print(f"🔍 EXPLORATION SESSION: {session_id}")
        print("=" * 80)
        print(f"   Entry URL: {session.entry_url}")
        print(f"   Status: {session.status}")
        print(f"   Strategy: {session.strategy}")
        print(f"   Pages Discovered: {session.pages_discovered}")
        print(f"   Flows Discovered: {session.flows_discovered}")
        print(f"   API Endpoints: {session.api_endpoints_discovered}")
        if session.duration_seconds:
            print(f"   Duration: {session.duration_seconds}s")
        print()

        # Show flows
        flows = store.get_session_flows(session_id)
        if flows:
            print("📋 Discovered Flows:")
            for f in flows:
                path_type = "✓" if f.is_success_path else "✗"
                print(f"   {path_type} {f.flow_name} ({f.flow_category}) - {f.step_count} steps")
            print()

        # Show API endpoints
        endpoints = store.get_session_api_endpoints(session_id)
        if endpoints:
            print("🔗 API Endpoints:")
            for e in endpoints[:10]:
                print(f"   {e.method} {e.url} ({e.call_count} calls)")
            if len(endpoints) > 10:
                print(f"   ... and {len(endpoints) - 10} more")
            print()

        print("=" * 80)
        sys.exit(0)

    # --- GENERATE REQUIREMENTS COMMAND ---
    if args.generate_requirements:
        import asyncio

        from orchestrator.workflows.requirements_generator import generate_requirements_from_exploration

        if not args.from_exploration:
            print("❌ --generate-requirements requires --from-exploration SESSION_ID")
            sys.exit(1)

        project_id = args.project_id or "default"

        try:
            result = asyncio.run(
                generate_requirements_from_exploration(
                    exploration_session_id=args.from_exploration, project_id=project_id
                )
            )

            print()
            print("=" * 80)
            print(f"✅ Generated {result.total_requirements} Requirements")
            print(f"   By Category: {json.dumps(result.by_category)}")
            print(f"   By Priority: {json.dumps(result.by_priority)}")
            print()
            print("Next steps:")
            print(f"  python orchestrator/cli.py --generate-rtm --project-id {project_id}")
            print("=" * 80)

        except ValueError as e:
            print(f"❌ Error: {e}")
            sys.exit(1)
        except Exception as e:
            if "cancel scope" in str(e).lower():
                pass
            else:
                print(f"\n❌ Requirements generation error: {e}")
                import traceback

                traceback.print_exc()

        sys.exit(0)

    # --- GENERATE RTM COMMAND ---
    if args.generate_rtm:
        import asyncio

        from orchestrator.workflows.rtm_generator import RtmGenerator

        project_id = args.project_id or "default"
        generator = RtmGenerator(project_id=project_id)

        try:
            result = asyncio.run(generator.generate_rtm(use_ai_matching=True))

            print()
            print("=" * 80)
            print("✅ RTM Generated")
            print(f"   Total Requirements: {result.total_requirements}")
            print(f"   Covered: {result.covered_requirements}")
            print(f"   Partial: {result.partial_requirements}")
            print(f"   Uncovered: {result.uncovered_requirements}")
            print(f"   Coverage: {result.coverage_percentage:.1f}%")
            print()

            # Show gaps
            if result.gaps:
                print(f"📋 Coverage Gaps ({len(result.gaps)} requirements without tests):")
                for gap in result.gaps[:5]:
                    print(f"   {gap['requirement_code']}: {gap['title']} ({gap['priority']})")
                if len(result.gaps) > 5:
                    print(f"   ... and {len(result.gaps) - 5} more")
                print()

            # Export if requested
            if args.rtm_export:
                exported = generator.export_rtm(format=args.rtm_export)
                if args.output:
                    Path(args.output).write_text(exported)
                    print(f"📄 Exported to: {args.output}")
                else:
                    print(exported)

            print("=" * 80)

        except Exception as e:
            if "cancel scope" in str(e).lower():
                pass
            else:
                print(f"\n❌ RTM generation error: {e}")
                import traceback

                traceback.print_exc()

        sys.exit(0)

    # --- RTM EXPORT ONLY ---
    if args.rtm_export and not args.generate_rtm:
        from orchestrator.workflows.rtm_generator import RtmGenerator

        project_id = args.project_id or "default"
        generator = RtmGenerator(project_id=project_id)

        exported = generator.export_rtm(format=args.rtm_export)
        if args.output:
            Path(args.output).write_text(exported)
            print(f"📄 RTM exported to: {args.output}")
        else:
            print(exported)
        sys.exit(0)

    # --- GENERATE API TESTS FROM EXPLORATION ---
    if args.generate_api_tests:
        import asyncio

        from orchestrator.workflows.api_test_from_exploration import ApiTestFromExploration

        if not args.from_exploration:
            print("❌ --generate-api-tests requires --from-exploration SESSION_ID")
            sys.exit(1)

        project_id = args.project_id or "default"

        print("=" * 80)
        print("🔌 GENERATING API TESTS FROM EXPLORATION DATA")
        print("=" * 80)
        print(f"   Session: {args.from_exploration}")
        print(f"   Project: {project_id}")
        print()

        try:
            generator = ApiTestFromExploration(project_id=project_id)
            result = asyncio.run(generator.generate(session_id=args.from_exploration))

            print()
            print("=" * 80)
            print(f"✅ Generated {len(result)} API test file(s)")
            for path in result:
                print(f"   - {path}")
            print()
            print("To run the generated tests:")
            print("  npx playwright test tests/generated/api/")
            print("=" * 80)

        except Exception as e:
            if "cancel scope" in str(e).lower():
                pass
            else:
                print(f"\n❌ API test generation error: {e}")
                import traceback

                traceback.print_exc()

        sys.exit(0)

    spec_path = args.spec

    if not spec_path:
        parser.print_help()
        sys.exit(1)

    spec_file = Path(spec_path)

    if not spec_file.exists():
        print(f"❌ Input file not found: {spec_path}")
        sys.exit(1)

    # --- OPENAPI/SWAGGER IMPORT ---
    if args.api_tests:
        import asyncio

        from orchestrator.workflows.openapi_processor import OpenApiProcessor

        print("=" * 80)
        print("📋 OPENAPI/SWAGGER → API TEST GENERATION")
        print("=" * 80)
        print(f"   Input: {spec_file.name}")
        if args.feature:
            print(f"   Feature filter: {args.feature}")
        print()

        project_id = args.project_id or "default"

        try:
            processor = OpenApiProcessor(project_id=project_id)
            result = asyncio.run(processor.process(str(spec_file), feature_filter=args.feature))

            print()
            print("=" * 80)
            print(f"✅ Generated {len(result)} API test file(s) from OpenAPI spec")
            for path in result:
                print(f"   - {path}")
            print()
            print("To run the generated tests:")
            print("  npx playwright test tests/generated/api/")
            print("=" * 80)

        except Exception as e:
            if "cancel scope" in str(e).lower():
                pass
            else:
                print(f"\n❌ OpenAPI processing error: {e}")
                import traceback

                traceback.print_exc()

        sys.exit(0)

    # --- EDGE CASE GENERATION ---
    if args.generate_edge_cases:
        import asyncio

        from orchestrator.workflows.api_edge_case_generator import ApiEdgeCaseGenerator

        print("=" * 80)
        print("🛡️ API EDGE CASE & SECURITY TEST GENERATION")
        print("=" * 80)
        print(f"   Spec: {spec_file.name}")
        print()

        project_id = args.project_id or "default"

        try:
            generator = ApiEdgeCaseGenerator(project_id=project_id)
            result = asyncio.run(generator.generate(str(spec_file)))

            print()
            print("=" * 80)
            print(f"✅ Generated {len(result)} edge case test file(s)")
            for path in result:
                print(f"   - {path}")
            print("=" * 80)

        except Exception as e:
            if "cancel scope" in str(e).lower():
                pass
            else:
                print(f"\n❌ Edge case generation error: {e}")
                import traceback

                traceback.print_exc()

        sys.exit(0)

    # --- AUTO-DETECT PRD SPECS ---
    # Check if this is a PRD-generated spec (multi-test format)
    from orchestrator.utils.spec_detector import SpecDetector, SpecType

    spec_info = SpecDetector.get_spec_info(spec_file)
    is_prd_spec = spec_info["type"] == SpecType.PRD

    if is_prd_spec and not args.native_generator and args.pipeline == "standard":
        print("=" * 80)
        print("🔍 PRD-GENERATED SPEC DETECTED")
        print("=" * 80)
        print(f"   Spec: {spec_file.name}")
        print(f"   Contains: {spec_info['test_count']} test cases")
        print(f"   Categories: {', '.join(spec_info['categories'])}")
        print()

        # If --split flag is provided, split and exit
        if args.split:
            print("📋 Splitting PRD spec into individual test files...")
            from orchestrator.utils.prd_spec_splitter import PRDSpecSplitter

            output_dir = Path(args.split_output_dir) if args.split_output_dir else None
            split_files, _groups = PRDSpecSplitter.split_spec(spec_file, output_dir)

            print(f"\n✅ Created {len(split_files)} individual test specs")
            if split_files:
                print(f"   Output: {split_files[0].parent}")
                print()
                print("To run individual tests:")
                print(f"  python orchestrator/cli.py {split_files[0]}")
            sys.exit(0)

        print("⚠️  This spec uses PRD format and must be run with Native Pipeline.")
        print("   Automatically switching to: --native-generator")
        print()
        print("💡 Tip: Use --split to create individual test files for each test case")
        print()
        args.native_generator = True

    # --- DETERMINE PIPELINE MODE ---
    # Native pipeline is now the default. Only use standard if explicitly requested.
    use_standard_pipeline = args.standard_pipeline or args.pipeline == "standard"

    # Legacy flag handling: if user uses old flags, show deprecation warning
    if args.ralph or args.native_healer or args.native_generator:
        print("⚠️  Note: --ralph, --native-healer, --native-generator flags are deprecated.")
        print("   Native pipeline is now the default. Use --hybrid for deep healing.")
        print()
        # Map legacy flags to new behavior
        if args.ralph or args.native_healer:
            args.hybrid = True

    # Ensure minimum iterations for hybrid
    if args.hybrid and args.max_iterations < 5:
        print("⚠️  Warning: Hybrid mode requires at least 5 iterations")
        print("   Auto-adjusting to 5")
        args.max_iterations = 5

    # --- PRD PIPELINE BRANCH ---
    if args.prd:
        if args.pipeline != "native":
            print("⚠️ PRD input requires --pipeline native. Switching to native mode.")
            args.pipeline = "native"

        print("=" * 80)
        print(f"📄 PROCESSING PRD: {spec_file.name}")
        print("=" * 80)

        # 1. Process PDF
        import asyncio

        from orchestrator.workflows.prd_processor import PRDProcessor

        processor = PRDProcessor()
        # Use filename stem as project name if not provided
        project_name = args.project_id or spec_file.stem.replace(" ", "-").lower()

        try:
            print(f"   Parsing and chunking PDF (Project: {project_name})...")
            result = processor.process_prd(str(spec_file), project_name)
            print(f"✅ PRD Processed: {len(result['features'])} features found.")
        except Exception as e:
            print(f"❌ PDF Processing failed: {e}")
            sys.exit(1)

        # 2. Native Planner
        from orchestrator.workflows.native_planner import NativePlanner

        planner = NativePlanner(project_id=project_name)

        specs_to_process = []
        try:
            if args.feature:
                print(f"   Generating spec for feature: {args.feature}")
                spec_path = asyncio.run(planner.generate_spec_for_feature(args.feature, project_name))
                specs_to_process.append(spec_path)
            else:
                print("   Generating specs for ALL features...")
                specs_to_process = asyncio.run(planner.generate_all_specs(project_name))

            print(f"✅ Generated {len(specs_to_process)} specs.")
        except Exception as e:
            print(f"❌ Planning failed: {e}")
            sys.exit(1)

        # 3. Native Generator & Healer Loop
        from orchestrator.workflows.native_generator import NativeGenerator
        from orchestrator.workflows.native_healer import NativeHealer

        generator = NativeGenerator()
        healer = NativeHealer()

        success_count = 0

        for spec in specs_to_process:
            print(f"\n--- Processing Spec: {spec.name} ---")
            try:
                # Generate Test
                test_path = asyncio.run(generator.generate_test(str(spec)))

                # Execute Test
                print(f"   Running test: {test_path.name}")
                cmd = f"npx playwright test '{test_path}' --project {args.browser}"
                result = run_command(cmd, stream_output=True, is_python=False)

                if result.returncode == 0:
                    print(f"✅ Test Passed: {test_path.name}")
                    success_count += 1
                else:
                    print("❌ Test Failed. Attempting to heal...")
                    # Heal Test
                    log_output = result.stdout + "\n" + result.stderr
                    fixed_code = asyncio.run(healer.heal_test(str(test_path), log_output))
                    if fixed_code:
                        print("   Re-running healed test...")
                        result = run_command(cmd, stream_output=True, is_python=False)
                        if result.returncode == 0:
                            print(f"✅ Healed Test Passed: {test_path.name}")
                            success_count += 1
                        else:
                            print("❌ Healed Test Failed Again.")
                    else:
                        print("⚠️ Healing failed or returned no code.")

            except Exception as e:
                print(f"⚠️ Error processing {spec.name}: {e}")

        print(f"\nSummary: {success_count}/{len(specs_to_process)} tests passed.")
        sys.exit(0)  # Exit after PRD pipeline

    # === HELPER FUNCTIONS ===
    def extract_test_name(path: Path) -> str:
        """Extract test name from spec file."""
        try:
            content = path.read_text()
            for line in content.splitlines():
                if line.startswith("# "):
                    return line.replace("# ", "").replace("Test:", "").strip()
        except Exception:
            pass
        return path.stem.replace("_", " ").title()

    def find_existing_test_code(spec: Path, spec_stem: str) -> Path:
        """Find existing generated test code for a spec."""
        # Check common locations for generated tests
        candidates = [
            Path(f"tests/generated/{spec_stem}.spec.ts"),
            Path(f"tests/generated/{spec_stem.replace('_', '-')}.spec.ts"),
            Path(f"tests/templates/{spec_stem}.spec.ts"),
            Path(f"tests/templates/{spec_stem.replace('_', '-')}.spec.ts"),
            Path(f"tests/generated/{spec_stem}.api.spec.ts"),
            Path(f"tests/generated/{spec_stem.replace('_', '-')}.api.spec.ts"),
            Path(f"tests/generated/api/{spec_stem}.spec.ts"),
            Path(f"tests/generated/api/{spec_stem}.api.spec.ts"),
        ]

        # Also try using the test name from the spec
        test_name = extract_test_name(spec)
        test_slug = test_name.lower().replace(" ", "-")
        candidates.extend(
            [
                Path(f"tests/generated/{test_slug}.spec.ts"),
                Path(f"tests/templates/{test_slug}.spec.ts"),
                Path(f"tests/generated/{test_slug}.api.spec.ts"),
                Path(f"tests/templates/{test_slug}.api.spec.ts"),
            ]
        )

        # Return first existing candidate
        for candidate in candidates:
            if candidate.exists():
                return candidate

        return None

    # --- SKILL MODE PIPELINE ---
    # Alternative to MCP-based pipeline for complex scenarios (network interception, multi-tab, etc.)
    if args.skill_mode and not args.prd:
        import asyncio

        from orchestrator.workflows.skill_executor import SkillExecutor

        print("=" * 80)
        print("🎭 SKILL MODE PIPELINE")
        print("=" * 80)
        print(f"   Spec: {spec_file.name}")
        print(f"   Timeout: {args.skill_timeout}ms")
        headless = args.skill_headless if args.skill_headless is not None else True
        print(f"   Headless: {headless}")
        print()
        print("⚠️  Skill mode generates a script template from the spec.")
        print("   For complex scenarios, consider using --run-skill with a custom script.")
        print()

        if args.run_dir:
            run_dir = Path(args.run_dir)
        else:
            run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            run_dir = Path(f"runs/{run_id}")
        run_dir.mkdir(parents=True, exist_ok=True)

        project_id = os.environ.get("PROJECT_ID") or args.project_id or "default"
        executor = SkillExecutor(project_id=project_id)

        # Extract target URL from spec
        spec_content = spec_file.read_text()
        url_pattern = r'Navigate to\s+(https?://[^\s\'"]+)'
        url_match = __import__("re").search(url_pattern, spec_content, __import__("re").IGNORECASE)
        target_url = url_match.group(1) if url_match else "https://example.com"

        # Generate script from spec
        script_content = executor.generate_script_from_spec(spec_content, target_url)

        # Save script for reference
        script_path = run_dir / "skill_script.js"
        script_path.write_text(script_content)
        print(f"📝 Generated script: {script_path}")
        print()
        print("Script template (customize as needed):")
        print("-" * 40)
        for _i, line in enumerate(script_content.split("\n")[:20], 1):
            print(f"  {line}")
        if len(script_content.split("\n")) > 20:
            print(f"  ... ({len(script_content.split(chr(10)))} lines total)")
        print("-" * 40)
        print()
        print("To execute this script:")
        print(f"  python orchestrator/cli.py --run-skill {script_path}")
        print()
        print("Or edit the script and run with custom logic.")
        sys.exit(0)

    # --- FULL NATIVE PIPELINE (DEFAULT) ---
    # Uses browser exploration at every stage: Native Planner → Native Generator → Native/Hybrid Healer
    if not use_standard_pipeline and not args.prd:
        import asyncio

        from orchestrator.workflows.full_native_pipeline import FullNativePipeline

        if args.run_dir:
            run_dir = Path(args.run_dir)
        else:
            run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            run_dir = Path(f"runs/{run_id}")
        run_dir.mkdir(parents=True, exist_ok=True)

        # Try existing code first if available
        code_path = None
        if args.try_code:
            code_path = Path(args.try_code)
        else:
            code_path = find_existing_test_code(spec_file, spec_file.stem)

        if code_path and code_path.exists():
            print(f"\n🔄 Trying existing code: {code_path}")

            # Create minimal artifacts for dashboard
            test_name = extract_test_name(spec_file)
            export_data = {
                "testFilePath": str(code_path),
                "code": code_path.read_text(),
                "dependencies": ["@playwright/test"],
                "notes": ["Reusing existing test code"],
            }
            (run_dir / "export.json").write_text(json.dumps(export_data, indent=2))
            (run_dir / "spec.md").write_text(spec_file.read_text())

            plan_data = {
                "testName": test_name,
                "steps": [],
                "specFileName": spec_file.name,
                "specFilePath": str(spec_file.absolute()),
                "browser": args.browser,
            }
            (run_dir / "plan.json").write_text(json.dumps(plan_data, indent=2))

            # Run existing test
            cmd = f"npx playwright test '{code_path}' --project {args.browser}"
            print(f"   Executing: {cmd}")
            result = run_command(cmd, stream_output=True, is_python=False)

            if result.returncode == 0:
                print("✅ Existing code passed! Skipping generation.")
                (run_dir / "status.txt").write_text("passed")
                sys.exit(0)
            else:
                print("⚠️ Existing code failed. Proceeding with healing...")
                existing_test_for_healing = str(code_path)  # Store for healing-only mode

        # Get project_id from environment (passed by API) or CLI args
        project_id = os.environ.get("PROJECT_ID") or args.project_id or "default"

        # Run the Full Native Pipeline
        pipeline = FullNativePipeline(project_id=project_id)

        # Determine if we should heal existing code or run full pipeline
        existing_test_path = existing_test_for_healing if "existing_test_for_healing" in dir() else None

        try:
            result = asyncio.run(
                pipeline.run(
                    spec_path=str(spec_file),
                    run_dir=run_dir,
                    browser=args.browser,
                    hybrid_healing=args.hybrid,
                    max_iterations=args.max_iterations,
                    skip_planning=False,
                    existing_test_path=existing_test_path,  # Triggers healing-only mode when set
                    force_api=getattr(args, "api", False),
                )
            )

            if result.get("success"):
                print("\n" + "=" * 80)
                print("✅ TEST PASSED")
                if result.get("attempts", 0) > 0:
                    print(f"   Healed after {result.get('attempts')} attempt(s)")
                print(f"   Test file: {result.get('test_path')}")
                print("=" * 80)
                # Write status file so the API wrapper can update DB
                status_file = run_dir / "status.txt"
                if not status_file.exists():
                    status_file.write_text("passed")
                sys.exit(0)
            else:
                print("\n" + "=" * 80)
                print("❌ TEST FAILED")
                print(f"   Stage: {result.get('stage', 'unknown')}")
                if result.get("error"):
                    print(f"   Error: {result.get('error')}")
                print("=" * 80)
                # Write status file so the API wrapper can update DB
                status_file = run_dir / "status.txt"
                if not status_file.exists():
                    status_file.write_text("error")
                sys.exit(1)

        except Exception as e:
            print(f"\n❌ Pipeline error: {e}")
            import traceback

            traceback.print_exc()
            (run_dir / "status.txt").write_text("error")
            sys.exit(1)

    # --- STANDARD SPEC PIPELINE (LEGACY) ---
    # Only runs if --standard-pipeline is explicitly provided
    if not use_standard_pipeline:
        # Should not reach here (native pipeline handles all cases above)
        print("❌ Error: Unexpected pipeline state. Use --standard-pipeline for classic mode.")
        sys.exit(1)

    print("⚠️  Using legacy standard pipeline (Plan→Operator→Exporter→Validator)")
    print("   Tip: Native pipeline is recommended for better reliability.\n")

    # Derive project_id from spec path if not provided
    project_id = args.project_id
    if not project_id:
        # Use parent folder name or spec name as project_id
        if spec_file.parent.name != "specs":
            project_id = spec_file.parent.name
        else:
            project_id = spec_file.stem

    # Set up environment for memory system
    env = os.environ.copy()
    env["MEMORY_PROJECT_ID"] = project_id or "default"
    env["MEMORY_ENABLED"] = "false" if args.no_memory else "true"
    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = Path(f"runs/{run_id}")

    run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print(f"🚀 CONVERTING TEST: {spec_file.name}")
    print("=" * 80)
    print()

    # --- STAGE 0: CHECK EXISTING CODE ---
    should_regenerate = True
    test_path = None

    if args.try_code:
        code_path = Path(args.try_code)
        if code_path.exists():
            print(f"🔄 Stage 0: Trying existing code: {code_path}")

            # Create export.json to expose code to UI immediately
            export_data = {"testFilePath": str(code_path), "code": code_path.read_text(), "dependencies": []}
            (run_dir / "export.json").write_text(json.dumps(export_data, indent=2))

            # Create minimal plan.json so UI shows the correct Test Name
            test_name = extract_test_name(spec_file)
            plan_data = {
                "testName": test_name,
                "steps": [],  # We don't have steps if we reuse code, UI will handle empty steps
                "specFileName": spec_file.name,
                "specFilePath": str(spec_file.absolute()),
                "browser": args.browser,
            }
            (run_dir / "plan.json").write_text(json.dumps(plan_data, indent=2))

            # Run the test
            output_dir = run_dir / "test-results"
            cmd = f"PLAYWRIGHT_OUTPUT_DIR='{output_dir}' npx playwright test '{code_path}' --project {args.browser}"
            print(f"   Executing: {cmd}")
            sys.stdout.flush()

            result = run_command(cmd, stream_output=True, is_python=False)

            if result.returncode == 0:
                print("✅ Existing code passed! Skipping generation.")

                run_data = {
                    "finalState": "passed",
                    "duration": 0,
                    "steps": [],
                    "notes": ["Reused existing code"],
                    "browser": args.browser,
                }
                (run_dir / "run.json").write_text(json.dumps(run_data, indent=2))

                print("✅ Run artifacts created.")
                return
            else:
                print("⚠️ Existing code failed. Attempting to heal...")
                if result.stdout:
                    print(result.stdout)
                if result.stderr:
                    print(result.stderr)

                # HEALING PATH: Skip generation and go straight to Validation (Step 4)
                should_regenerate = False
                test_path = str(code_path)
                print("🔧 Skipping plan/execute stages -> Jumping to Self-Healing (Stage 4).")
                print()

    if should_regenerate:
        # --- STAGE 1: PLAN ---
        print("📋 Stage 1: Creating test plan...")
        # Invoke inner modules using -m to ensure package resolution works
        result = run_command(f"-u -m orchestrator.workflows.planner '{spec_path}'", env=env)
        print_output(result)

        plan_src = Path("runs/test_plan.json")
        if plan_src.exists():
            shutil.move(plan_src, run_dir / "plan.json")

            # INJECT METADATA
            try:
                plan_data = json.loads((run_dir / "plan.json").read_text())
                plan_data["specFileName"] = spec_file.name
                plan_data["specFilePath"] = str(spec_file.absolute())
                plan_data["browser"] = args.browser
                (run_dir / "plan.json").write_text(json.dumps(plan_data, indent=2))
            except Exception as e:
                print(f"⚠️ Failed to inject metadata: {e}")

            print(f"✅ Plan saved to: {run_dir / 'plan.json'}")
        else:
            print("❌ Plan not found")
            if result.stdout:
                print(result.stdout)
            sys.exit(1)

        # Test Plan Summary
        try:
            plan = json.loads((run_dir / "plan.json").read_text())
            print(f"   Test: {plan.get('testName')}")
            print(f"   Steps: {len(plan.get('steps', []))}")
        except Exception as e:
            print(f"⚠️ Could not read plan summary: {e}")
        print()

        # Interactive Review Loop
        if args.interactive:
            while True:
                print("=" * 40)
                print("🤔 Plan Review")
                print("  [c] Continue to execution")
                print("  [e] Edit plan manually")
                print("  [q] Quit")
                choice = input("Option: ").lower().strip()

                if choice == "q":
                    sys.exit(0)
                elif choice == "e":
                    print(f"✏️  Edit the file at: {run_dir / 'plan.json'}")
                    input("Press Enter when done editing...")
                    try:
                        plan = json.loads((run_dir / "plan.json").read_text())
                        print("✅ Plan reloaded.")
                    except Exception as e:
                        print(f"❌ Invalid JSON: {e}")
                        continue
                elif choice == "c":
                    break

        # --- STAGE 2: EXECUTE ---
        print("🤖 Stage 2: Executing test plan...")

        cmd = f"-u -m orchestrator.workflows.plan_executor '{run_dir / 'plan.json'}' '{run_dir}'"
        if args.interactive:
            cmd += " --interactive"
        if args.native_generator:
            cmd += " --native-generator"

        result = run_command(cmd, stream_output=True, interactive=args.interactive, env=env)
        if not args.interactive:
            print_output(result)

        run_file = run_dir / "run.json"
        if run_file.exists():
            print(f"✅ Run saved to: {run_file}")
            try:
                run = json.loads(run_file.read_text())
                print(f"   Final state: {run.get('finalState')}")
                print(f"   Duration: {run.get('duration', 0):.1f}s")
            except Exception:
                pass
        else:
            print("❌ Run not found")
            sys.exit(1)

        # --- REPORT GENERATION ---
        try:
            from orchestrator.reporting.report_generator import ReportGenerator

            generator = ReportGenerator(str(run_dir))
            generator.generate()
        except Exception as e:
            print(f"⚠️ Report generation failed: {e}")
        print()

        # --- STAGE 3: EXPORT ---
        print("📤 Stage 3: Generating test code...")

        # Check if operator already generated the code
        run_file = run_dir / "run.json"
        test_path = None

        if run_file.exists():
            try:
                run_data = json.loads(run_file.read_text())
                generated_code = run_data.get("generatedCode")
                test_path = run_data.get("testFilePath")

                if generated_code and test_path:
                    # Use code generated by operator - write directly to file
                    test_file = Path(test_path)
                    test_file.parent.mkdir(parents=True, exist_ok=True)
                    test_file.write_text(generated_code)
                    print("✅ Test code written directly from execution")
                    print(f"   Test file: {test_path}")

                    # Save export.json for compatibility
                    export_data = {
                        "testFilePath": test_path,
                        "code": generated_code,
                        "dependencies": ["@playwright/test"],
                        "notes": ["Generated during execution with actual values"],
                    }
                    (run_dir / "export.json").write_text(json.dumps(export_data, indent=2))
                else:
                    # Fallback to exporter agent
                    print("   (Using exporter agent as fallback)")
                    result = run_command(f"-u -m orchestrator.workflows.exporter '{run_dir / 'run.json'}'", env=env)
                    print_output(result)

                    export_file = run_dir / "export.json"
                    if export_file.exists():
                        export_data = json.loads(export_file.read_text())
                        test_path = export_data.get("testFilePath")
                        print(f"✅ Export saved to: {export_file}")
                        print(f"   Test file: {test_path}")
                    else:
                        print("❌ Export not found")
                        sys.exit(1)
            except Exception as e:
                print(f"⚠️ Error reading run: {e}")
                sys.exit(1)
        else:
            print("❌ Run file not found")
            sys.exit(1)
        print()

    # --- STAGE 4: VALIDATE ---
    if test_path:
        # Choose validator based on mode
        if args.hybrid:
            print("🔄 Stage 4: Hybrid Mode Validation...")
            print("   Phase 1: Native Healing (1-3 attempts)")
            print(f"   Phase 2: Ralph Loop (4-{args.max_iterations} attempts)")
            print(f"   Test file: {test_path}")
            print(f"   Browser: {args.browser}")
            print()

            plan_file = run_dir / "plan.json"
            if plan_file.exists():
                print(f"   📋 Plan file: {plan_file}")
            plan_arg = f"'{plan_file}'" if plan_file.exists() else "''"
            spec_arg = f"'{spec_path}'"

            # Call ralph_validator with hybrid=true
            result = run_command(
                f"-u -m orchestrator.workflows.ralph_validator '{test_path}' '{run_dir}' '{args.browser}' {args.max_iterations} {plan_arg} {spec_arg} false true",
                stream_output=True,
            )
            validation_file = run_dir / "hybrid_validation.json"

        elif args.ralph:
            print("🔄 Stage 4: Ralph Mode Validation (deep iteration)...")
            print(f"   Max iterations: {args.max_iterations}")
            print(f"   Test file: {test_path}")
            print(f"   Browser: {args.browser}")
            print()
            # Stream Ralph output for visibility
            # Include plan and spec file for context
            plan_file = run_dir / "plan.json"
            if plan_file.exists():
                print(f"   📋 Plan file: {plan_file}")
            plan_arg = f"'{plan_file}'" if plan_file.exists() else "''"
            spec_arg = f"'{spec_path}'"
            native_healer_arg = "true" if getattr(args, "native_healer", False) else "false"

            result = run_command(
                f"-u -m orchestrator.workflows.ralph_validator '{test_path}' '{run_dir}' '{args.browser}' {args.max_iterations} {plan_arg} {spec_arg} {native_healer_arg} false",
                stream_output=True,
            )
            validation_file = run_dir / "ralph_validation.json"
        else:
            print("🔍 Stage 4: Standard Validation (max 7 attempts)...")
            # Pass spec and plan for context
            spec_arg = f"'{spec_path}'"
            plan_file = run_dir / "plan.json"
            plan_arg = f"'{plan_file}'" if plan_file.exists() else "''"
            result = run_command(
                f"-u -m orchestrator.workflows.validator '{test_path}' '{run_dir}' '{args.browser}' {spec_arg} {plan_arg}",
                stream_output=True,
            )
            validation_file = run_dir / "validation.json"

        validation_data = {}
        if validation_file.exists():
            try:
                validation_data = json.loads(validation_file.read_text())
                status = validation_data.get("status")
                if status == "success":
                    iterations = validation_data.get("iterations", validation_data.get("attempts", 1))
                    mode = validation_data.get("mode", "standard")

                    # Hybrid mode specific display
                    if mode == "hybrid":
                        phase = validation_data.get("phaseSucceeded", "unknown")
                        print()
                        print("=" * 80)
                        print(f"✅ Hybrid Validation PASSED after {iterations} iterations")
                        print(f"   Succeeded in: {phase.title()} Phase")
                        if phase == "ralph":
                            native = validation_data.get("nativeIterations", 0)
                            ralph = validation_data.get("ralphIterations", 0)
                            print(f"   Native: {native} attempts")
                            print(f"   Ralph: {ralph} iterations")
                        print("=" * 80)
                    else:
                        mode_label = "Ralph iterations" if mode == "ralph" else "attempt(s)"
                        print()
                        print("=" * 80)
                        print(f"✅ Validation PASSED after {iterations} {mode_label}")
                        print("=" * 80)
                elif status == "crashed":
                    print()
                    print("=" * 80)
                    print(f"💥 Validation CRASHED: {validation_data.get('message')}")
                    print(f"   Iterations before crash: {validation_data.get('iterations', 0)}")
                    if validation_data.get("error"):
                        print(
                            f"   Error: {validation_data.get('error')[:100]}{'...' if len(validation_data.get('error', '')) > 100 else ''}"
                        )
                    print("=" * 80)
                else:
                    print()
                    print(f"⚠️  Validation failed: {validation_data.get('message')}")
            except Exception as e:
                print(f"⚠️  Could not parse validation result: {e}")
        else:
            print(f"⚠️  Validation file not found: {validation_file}")
    print()

    # --- SUMMARY ---
    print("=" * 80)
    print("✅ CONVERSION COMPLETE")
    print("=" * 80)
    if test_path:
        print(f"Test file: {test_path}")
    print(f"Artifacts: {run_dir}")
    if validation_data.get("status") == "success":
        print("✅ Test validated and passing")
    print()
    if test_path:
        print("To run the test:")
        print(f"  npx playwright test {test_path}")
    print()


if __name__ == "__main__":
    main()
