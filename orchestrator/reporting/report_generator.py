"""
Report Generator Module
Generates HTML reports and GIFs for Quorvex AI runs.
"""

import base64
import json
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None


class ReportGenerator:
    def __init__(self, run_dir: str):
        self.run_dir = Path(run_dir)
        self.run_data = {}
        self.screenshots: list[Path] = []

        # Load run data if exists
        run_file = self.run_dir / "run.json"
        if run_file.exists():
            self.run_data = json.loads(run_file.read_text())

        # Find screenshots
        self.screenshots = sorted(list(self.run_dir.glob("*.png")))

    def generate(self):
        """Generate all reports"""
        print(f"📊 Generating reports for run in {self.run_dir}")
        self._generate_gif()
        self._generate_html()

    def _generate_gif(self):
        """Create an animated GIF from screenshots"""
        if not self.screenshots:
            print("   ⚠️ No screenshots found for GIF generation")
            return

        if not Image:
            print("   ⚠️ Pillow not installed. Skipping GIF generation.")
            return

        print(f"   🎞️ Creating execution GIF from {len(self.screenshots)} screenshots...")

        images = []
        try:
            for screenshot in self.screenshots:
                img = Image.open(screenshot)
                # Resize for manageable file size if needed, keeping aspect ratio
                # img.thumbnail((800, 800))
                images.append(img)

            if images:
                output_path = self.run_dir / "execution.gif"
                # Duration is milliseconds per frame
                images[0].save(
                    output_path,
                    save_all=True,
                    append_images=images[1:],
                    duration=1000,
                    loop=0,
                    optimize=True,
                )
                print(f"   ✅ GIF saved to: {output_path}")
        except Exception as e:
            print(f"   ❌ Failed to create GIF: {e}")

    def _generate_html(self):
        """Create a standalone HTML report"""
        print("   📄 Creating HTML report...")

        test_name = self.run_data.get("testName", "Unknown Test")
        status = self.run_data.get("finalState", "unknown").upper()
        duration = self.run_data.get("duration", 0)
        steps = self.run_data.get("steps", [])

        # Determine status color
        status_color = "#10b981" if status == "PASSED" else "#ef4444"

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Report: {test_name}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 20px; background: #f3f4f6; color: #1f2937; }}
        .container {{ max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #e5e7eb; padding-bottom: 20px; margin-bottom: 20px; }}
        .title h1 {{ margin: 0; font-size: 24px; }}
        .meta {{ color: #6b7280; font-size: 14px; margin-top: 5px; }}
        .badge {{ padding: 6px 12px; border-radius: 20px; font-weight: bold; color: white; background-color: {status_color}; }}
        .summary {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: #f9fafb; padding: 15px; border-radius: 8px; text-align: center; }}
        .card .label {{ display: block; color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
        .card .value {{ font-size: 24px; font-weight: bold; margin-top: 5px; }}
        .gif-container {{ margin-bottom: 40px; text-align: center; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
        .gif-container img {{ max-width: 100%; height: auto; }}
        .step-list {{ list-style: none; padding: 0; }}
        .step {{ border: 1px solid #e5e7eb; border-radius: 8px; margin-bottom: 15px; overflow: hidden; }}
        .step-header {{ background: #f9fafb; padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; }}
        .step-title {{ font-weight: 600; }}
        .step-status {{ font-size: 12px; padding: 2px 8px; border-radius: 10px; }}
        .status-success {{ background: #d1fae5; color: #065f46; }}
        .status-failed {{ background: #fee2e2; color: #991b1b; }}
        .step-body {{ padding: 20px; display: none; border-top: 1px solid #e5e7eb; }}
        .step.open .step-body {{ display: block; }}
        .step-detail {{ display: grid; grid-template-columns: 120px 1fr; gap: 10px; margin-bottom: 10px; font-size: 14px; }}
        .label {{ font-weight: 600; color: #4b5563; }}
        .screenshot {{ margin-top: 15px; border: 1px solid #e5e7eb; border-radius: 4px; overflow: hidden; }}
        .screenshot img {{ width: 100%; display: block; }}
        .error-message {{ background: #fee2e2; color: #991b1b; padding: 10px; border-radius: 4px; margin-top: 10px; font-family: monospace; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">
                <h1>{test_name}</h1>
                <div class="meta">Run ID: {self.run_dir.name} • {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
            </div>
            <div class="badge">{status}</div>
        </div>

        <div class="summary">
            <div class="card">
                <span class="label">Duration</span>
                <div class="value">{duration:.1f}s</div>
            </div>
            <div class="card">
                <span class="label">Steps</span>
                <div class="value">{len(steps)}</div>
            </div>
            <div class="card">
                <span class="label">Screenshots</span>
                <div class="value">{len(self.screenshots)}</div>
            </div>
        </div>
"""

        # Embed GIF if exists
        gif_path = self.run_dir / "execution.gif"
        if gif_path.exists():
            # Read GIF as base64 to embed directly
            try:
                gif_b64 = base64.b64encode(gif_path.read_bytes()).decode("utf-8")
                html_content += f"""
        <div class="gif-container">
            <img src="data:image/gif;base64,{gif_b64}" alt="Execution Replay">
        </div>
"""
            except Exception:
                pass

        html_content += """
        <h2>Execution Log</h2>
        <ul class="step-list">
"""

        for i, step in enumerate(steps):
            step_num = step.get("stepNumber", i + 1)
            action = step.get("action", "UNKNOWN").upper()
            description = step.get("description", "")
            result = step.get("result", "unknown")
            error = step.get("error")
            target = step.get("target", "")

            status_class = "status-success" if result == "success" else "status-failed"

            # Find matching screenshot
            # Assuming linear mapping loosely, or we could match timestamps if we had them perfectly synced.
            # Ideally steps should have a 'screenshot' field with filename.
            # plan_executor.py doesn't strictly name screenshots by step yet, but let's try to match.
            # Operator prompt instructed: "Save screenshots to current directory"
            # It didn't enforce naming convention.
            # But usually they come out as screenshot_1.png etc. if agent follows instructions?
            # Actually agent names them arbitrary.
            # We will just display ALL screenshots at the bottom or try to fuzzy match?
            # Let's keep it simple: no per-step screenshot embedding for now unless explicit.

            html_content += f"""
            <li class="step open">
                <div class="step-header" onclick="this.parentElement.classList.toggle('open')">
                    <span class="step-title">Step {step_num}: {action}</span>
                    <span class="step-status {status_class}">{result.upper()}</span>
                </div>
                <div class="step-body">
                    <div class="step-detail"><span class="label">Description:</span> <span>{description}</span></div>
                    <div class="step-detail"><span class="label">Target:</span> <span>{target}</span></div>
                    <div class="step-detail"><span class="label">Selector:</span> <code>{step.get("selector", "N/A")}</code></div>
                    {f'<div class="error-message">{error}</div>' if error else ""}
                </div>
            </li>
"""

        html_content += """
        </ul>
    </div>
</body>
</html>
"""

        output_file = self.run_dir / "report.html"
        output_file.write_text(html_content, encoding="utf-8")
        print(f"   ✅ Report saved to: {output_file}")
