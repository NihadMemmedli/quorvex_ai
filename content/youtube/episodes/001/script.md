# AI-Generated Playwright Tests Failed — Now What?

## Demo 001 Script

### 0:00-0:30 Cold Open

We are starting on a red checkout failure in Quorvex Demo Shop. The generated Playwright run did not pass, and that is the point.

Here we have a commerce project called Quorvex Demo Shop. The dashboard already tells us the release is risky: failed checkout tests, flaky state restoration, a slow checkout retry, and a database quality run with customer and order issues.

Most demo videos start with a perfect generated test. Real QA work does not look like that. Real QA work starts when generated tests fail, selectors drift, validation changes, the database disagrees with the UI, and someone has to decide what matters.

This walkthrough shows how Quorvex AI turns those failures into organized QA evidence.

### 0:30-1:15 Problem

AI-generated tests and QA agents are useful, but they are not magic. They can produce brittle selectors. They can expose a real bug and still need a human review. They can fail because the application changed, or because the generated assertion was wrong.

The useful system is not the one that pretends every generated test is perfect. The useful system is the one that keeps the failure explainable.

For a QA team, that means you need specs, historical runs, logs, failure categories, agent findings, generated test ideas, and enough evidence to decide the next action.

That is the workflow in this demo.

### 1:15-2:30 Project Setup

I am starting from the project selector and choosing Quorvex Demo Shop.

This project is seeded for the demo, so the data is deterministic. I am not depending on a live agent run behaving perfectly during a recording. The point is to show the workflow clearly: what a QA engineer sees after checkout coverage has been generated and a nightly run found problems.

The specs cover login, cart pricing, discount codes, payment validation, checkout state, and order confirmation.

The run history includes passed tests, failed tests, a healed checkout run, a flaky checkout-state case, and a slow timeout. That gives us enough signal to talk like a real QA review instead of just clicking through a platform tour.

### 2:30-4:00 Failed Run Walkthrough

Now I will open the failed run for checkout payment validation.

The first failure is selector drift. The test was looking for a Pay now button, but the current page has a hidden old button and a visible submit control with a more stable test id.

That is not the same as a product bug. It is automation maintenance. The run details show the stage, the failure reason, and the log evidence. A QA engineer can fix the locator or ask Quorvex to generate a revised Playwright test from the same spec.

The next failure is more serious: payment validation regression. The test expected an expired card to be blocked with an inline message. Instead, the page showed payment authorized.

That looks like a product defect. The difference matters. Quorvex is not just saying failed. It is separating selector drift from a validation regression, so the team can route the work correctly.

I also have a cart total mismatch: expected 86 dollars and 40 cents, but the UI showed 91 dollars and 40 cents after a discount. That points to pricing logic or duplicated shipping.

Finally, there is a checkout-state timeout after refresh. That one is marked flaky because historical runs show both passing and failing outcomes.

### 4:00-5:45 Agent Findings

Now I will open the agent run called Checkout Failure Triage.

This is a completed report, not a live agent performance demo. It shows what I want from an agent after a failed run: findings, evidence, test ideas, and follow-up actions.

The first finding says the payment button locator drifted after a copy and layout change. The evidence points to the failed run log where the locator resolved to a hidden element.

The second finding is the important one: expired card validation allows order submission. The evidence says the expected inline error was absent and the run captured Payment authorized text.

The third finding connects the UI mismatch to cart pricing. The frontend total diverges from the pricing preview.

From here, the test ideas are actionable. One suggestion is to add an API-backed cart total contract before checkout. Another is to retry checkout after an expired session and make sure the customer returns to the original checkout path.

This is the value of the agent layer. It does not replace QA ownership. It collects context and proposes work that a QA engineer can review.

### 5:45-7:00 Specs and Coverage

Next I will open the specs.

The checkout payment validation spec is written in plain markdown. It says what the user does, what data is used, and what the expected result is. This is important because the generated Playwright code should be traceable back to the requirement, not just appear as a random script.

The cart total spec describes the exact pricing expectation: line items, discount, tax, shipping, and total. That makes the failed assertion useful. We can tell whether the test is wrong, the UI is wrong, or the backend preview is wrong.

The login recovery and checkout state specs cover edge cases that are easy to miss in a happy-path demo. Session expiry and page refresh are exactly where checkout flows become flaky.

The generated tests are not the source of truth. The specs are the source of intent. The tests are executable coverage that should evolve as the app changes.

### 7:00-8:15 Quality Signals

Now I will switch to database testing.

This is not a full database-testing tour. I just want to show why UI failures often need backend evidence.

The demo database run has passing and failing checks. It catches duplicate customers, invalid email format, a negative order item quantity, and a payment total that does not match the order total.

Those issues connect directly to checkout quality. If a payment run fails in the browser, and the database also shows order/payment mismatches, the QA story becomes stronger.

The dashboard then gives the broader signal: pass/fail trend, failure categories, flaky tests, and slowest tests. A QA lead can decide whether the release risk is mostly automation maintenance, product regression, data quality, or performance.

### 8:15-9:30 Recap

Here is the workflow again.

We started with failed checkout tests. We inspected a specific failure and separated selector drift from product regression. We reviewed an agent report with findings, evidence, test ideas, and follow-up actions. We connected specs to generated Playwright work. Then we looked at database and dashboard signals to understand release risk.

That is the shape of Quorvex AI: generate and organize Playwright QA work, keep evidence attached, and make failures reviewable.

Teams still own the code. Teams still decide what should ship. Quorvex helps collect the context faster and keeps the work from turning into scattered logs, screenshots, and chat messages.

### 9:30-10:00 CTA

If you want to try this exact demo, seed the project with `make youtube-demo-seed` and open Quorvex Demo Shop.

Star the repo if this workflow is useful, and comment with the QA workflow you want next: API contract testing, PR test selection, database quality checks, or agent-assisted Playwright maintenance.
