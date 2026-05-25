# Quorvex AI in 10 Minutes: Generate Your First Playwright Test

> If your team already uses Playwright, the hard part is not believing that automated tests matter. The hard part is writing enough useful coverage without spending every sprint inside selectors, waits, setup code, and flaky failures.

> Quorvex AI is built around one practical idea: let agents help create and validate tests, but keep the final output as normal Playwright code your team can inspect, commit, and run in CI.

> In this tutorial, I will show the first workflow end to end. We will start from the repo, open the dashboard, describe a small test in plain English, run it through the pipeline, and inspect the generated Playwright file.

> The point is not to watch a polished demo and assume everything is automatic. The point is to understand the loop: write a clear spec, let Quorvex plan against the target, generate a test, validate it in a browser, and then review the output like engineering work.

> Start on the GitHub repo. The README gives the product shape: Quorvex is self-hosted, AI-assisted, and code-first. It can work with specs, PRDs, exploration, API checks, load tests, security checks, database checks, CI gates, and autonomous coverage discovery, but the first video should stay narrow.

> The fastest path is the minimal setup. For a local evaluation, it keeps the number of services low while still showing the real dashboard and generation flow. For production or team usage, Quorvex also supports the full stack with queues, storage, browser viewing, credentials, schedules, and integrations.

> If you want the quickest trial, use the minimal README. If you want to evaluate the full platform shape, use the main getting-started tutorial. Either way, the first target is simple: get the backend and dashboard running, then generate one test.

> Before adding credentials, pause on the model configuration. Quorvex uses an Anthropic-compatible setup. That can point to Anthropic, OpenRouter, Z.ai, or another compatible endpoint, depending on how you run it. The exact provider matters less than having a working token and a model that can follow the generation workflow.

> Once the app is running, open the dashboard. The dashboard is not just decoration around a CLI. It is where a team can create specs, inspect runs, review artifacts, track requirements, see regression history, and understand what the agents did.

> For the first video, keep the dashboard tour brief. We only need enough context to create or run a spec. Later videos can go deeper into requirements, API testing, PRDs, autonomous missions, and CI quality gates.

> Now move to the most important object in the first workflow: the spec. A Quorvex spec is just markdown. It names the test, describes the steps, and states the expected outcome. That makes the request reviewable before any code is generated.

> This is an important design choice. If the input is vague, the generated code will probably be vague too. A good spec gives the agent a clear target URL, a small user flow, and an observable outcome.

> For the first run, use a simple public page or one workflow in your own application. Keep it small. A good first test proves the pipeline and gives you generated code that is easy to inspect.

> In the getting-started tutorial, the example checks a dynamic loading page and verifies that the Hello World message appears after the loading step completes. That is not a business-critical workflow, but it is a good first proof because the expected result is easy to see.

> After the spec is ready, run the pipeline. Under the hood, Quorvex is not trying to give you a cute code snippet. The workflow is planning, generation, validation, and repair attempts when failures are concrete enough to address.

> Planning matters because web tests need sequencing. The agent has to understand where to navigate, what to click, what to wait for, and what assertion proves the flow worked.

> Browser context matters because selectors are not reliable when they are guessed from a prompt alone. A real browser gives the system evidence about what is actually on the page.

> Generation matters because the output should be standard Playwright TypeScript. This is the key ownership point. You should be able to open the file, read it, edit it, commit it, and run it without Quorvex sitting in the middle of every future CI job.

> Validation matters because generated code is only useful after it runs. A failing generated test is not worthless, but it is not done. The run artifacts tell you whether the failure is in the target app, the spec, timing, selectors, authentication, or the generated code itself.

> When the run completes, do not just look for a green status. Open the generated file. Check the locators. Check the assertions. Check whether the code reads like something you would accept in a pull request.

> This review habit is what separates useful AI automation from throwaway demos. If the test is readable and the assertion is meaningful, the generated file can become part of the suite. If it is too broad, too brittle, or too clever, edit it or improve the spec and run again.

> If validation fails, the run artifacts still matter. Screenshots, logs, browser evidence, and failure details make the problem concrete. The goal is not magic. The goal is a faster loop with evidence.

> In a real team, this also changes the review conversation. Instead of asking whether AI wrote a perfect test, the better question is whether the system produced a useful candidate with enough evidence for an engineer or QA automation owner to make a decision.

> This workflow is why Quorvex is self-hosted and code-first. AI helps with planning, generation, validation, exploration, and repair, but your team keeps normal tests that can run without an AI dependency during every CI job.

> That also means you can start small. You do not need to migrate a whole test suite. Pick one flow with clear value. Generate one test. Review the output. Run it locally. Then decide whether the next workflow should be another UI test, an API check, a PRD-to-tests flow, or a CI gate.

> If you are evaluating Quorvex for a team, I would measure three things after this first run. First, did it save time compared with writing the same Playwright test by hand? Second, is the generated code readable enough to maintain? Third, did the artifacts explain what happened when the run passed or failed?

> If the answer is no, the feedback is still useful. It tells us whether the spec format needs better guidance, whether the dashboard needs clearer evidence, or whether the generation pipeline needs a stronger constraint.

> To try this yourself, open the repo, follow the minimal setup, and create one spec from a real workflow your team cares about. If that first generated test is useful, the next step is to add PRD coverage, API checks, regression batches, and CI quality gates.

> The repo is https://github.com/NihadMemmedli/quorvex_ai, and the docs are at https://nihadmemmedli.github.io/quorvex_ai/. Star Quorvex AI if you want to follow the project, and send feedback from real Playwright workflows. That feedback is the most useful signal for what to improve next.
