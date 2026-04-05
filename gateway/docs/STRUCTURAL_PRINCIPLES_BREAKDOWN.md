# STRUCTURAL PRINCIPLES BREAKDOWN
## Every Principle Converted to Executable DO/DON'T/MEASURE Rules
### Date: 2026-02-19 | Source: Session 12 Research (4 documents)
### Status: REFERENCE DOCUMENT -- Use for gate/hook/check implementation

---

## TABLE OF CONTENTS

1. [Amazon Principles (4 + 3H Framework)](#part-1-amazon-principles)
2. [Nike 11 Maxims](#part-2-nike-11-maxims)
3. [Musk 5 Operational Principles](#part-3-musk-5-operational-principles)
4. [Protocol Failure Terms -- 11 Executable Definitions](#part-4-protocol-failure-terms----11-executable-definitions)
5. [Cross-Reference Matrix](#appendix-cross-reference-matrix)
6. [8 Anti-Patterns from Covey/Alignment Research](#appendix-8-anti-patterns)
7. [Three Laws of Commercial Readiness](#appendix-three-laws-of-commercial-readiness)

---

# PART 1: AMAZON PRINCIPLES

---

## A1: Innovation Driven by Customer Needs

**Original Principle**: "Don't innovate for innovation's sake. Solve REAL customer problems." Amazon Prime was born from the insight that customers valued fast free shipping.

**Software Translation**: Every new feature, module, or architectural component must trace back to a specific customer pain point. Infrastructure that does not make the customer's experience better is waste. Innovation is the MEANS; customer relief is the END.

**DO THIS**:
1. Before building any feature, write a 1-sentence customer problem statement: "The customer cannot [verb] because [blocker]."
2. Link every task to a user journey from PRODUCT_ACCEPTANCE_TESTS.yaml.
3. When proposing infrastructure (hooks, governance, tools), state the customer-facing incident it prevents or the user flow it accelerates.

**DON'T DO THIS**:
1. Build governance layers, hooks, or internal tooling without a documented customer-facing impact within 5 sessions.
2. Add features because they exist in a competitor without verifying customers actually need them.
3. Start implementation before answering: "Which paying customer does this help, and how?"

**Measurement**: Every task in session_focus has a `customer_problem` field. If the field is empty or says "internal improvement" for more than 40% of tasks in a session, the principle is violated. Pass/Fail: Can you trace this task to a line in PRODUCT_ACCEPTANCE_TESTS.yaml? Yes = pass. No = fail.

**Gate Candidate**: YES -- Prompt hook on Task tool launch. Haiku checks agent prompt for a customer problem statement. Advisory (WARN) if missing. Estimated cost: ~$0.001/agent launch.

---

## A2: Personalization and Convenience

**Original Principle**: "Use data to personalize every interaction. One-click ordering, same-day delivery, seamless returns. Make it as convenient as possible."

**Software Translation**: Minimize friction at every step. Every additional click, page load, or form field is a cost to the user. Measure time-to-value and optimize relentlessly.

**DO THIS**:
1. Enforce time-to-first-value under 5 minutes for new users (signup to "aha moment" in 3 actions or fewer).
2. Measure and enforce LCP under 2.5s, INP under 200ms, CLS under 0.1 on every page.
3. Build graceful degradation -- partial failures show partial results, not error screens.

**DON'T DO THIS**:
1. Require registration before the user sees any value (registration wall before value).
2. Show raw error messages ("500 Internal Server Error", "undefined", "null") to users.
3. Ignore mobile -- every UI must work at 375px with 44x44px touch targets.

**Measurement**: Lighthouse performance score >= 90 on all user-facing pages. Signup steps <= 3. Time from first visit to completing core action < 5 minutes. Pass/Fail: Does it meet these thresholds? Yes = pass. No = fail.

**Gate Candidate**: YES -- CI check. Lighthouse CI on every frontend deployment. Fails build if performance score < 90 or any Core Web Vital exceeds threshold.

---

## A3: Empowering Customers with Information

**Original Principle**: "Transparency builds trust. Detailed descriptions, reviews, ratings. Help customers make informed decisions."

**Software Translation**: Never leave the user guessing. Every state, every price, every error, every wait time must be communicated clearly. The user should never wonder "what is happening?"

**DO THIS**:
1. Every async operation has a visible loading state (skeleton screens, not spinners).
2. Every error message includes: what happened + what the user can do next.
3. Price is visible before signup. Payment flow completes in under 60 seconds. Self-service cancellation in under 3 clicks.

**DON'T DO THIS**:
1. Show blank/empty screens when data is loading or missing (use empty state illustrations with CTA).
2. Swallow errors silently (`catch(e) {}` with no user feedback).
3. Hide pricing, terms, or cancellation behind multiple pages or support tickets.

**Measurement**: Zero instances of "undefined", "null", "NaN", or programmer jargon in production UI. Every async operation has a loading state. Every error handler produces user-facing feedback. Pass/Fail: Can you find ANY user-facing text that a non-programmer would not understand? If yes = fail.

**Gate Candidate**: YES -- CI lint rule. Custom ESLint rule flags bare `catch(e) {}` blocks. Playwright E2E checks for "undefined"/"null"/"NaN" in rendered DOM. Build fails on violation.

---

## A4: Long-Term Thinking

**Original Principle**: "Willing to forego short-term profits for long-term customer loyalty. Invest heavily in customer experience even if payoff takes years."

**Software Translation**: Architectural decisions optimize for maintainability and customer trust over speed of initial delivery. Technical debt is tracked and retired, not accumulated silently.

**DO THIS**:
1. Every hack/shortcut gets a tracked task with a deadline (max 5 sessions before resolution).
2. Invest in structural enforcement (hooks, middleware, DB constraints) over text rules.
3. Build self-service features (cancellation, refunds, data export) even when support could handle them manually.

**DON'T DO THIS**:
1. Ship known-broken features to "get something out" -- a broken feature is worse than a missing feature (it lies to the user).
2. Accumulate more than 10 unresolved tech debt items without a retirement plan.
3. Sacrifice security, data integrity, or user trust for shipping speed.

**Measurement**: Tech debt tracker has fewer than 10 open items. Every item has a target session. Items open > 5 sessions are flagged CRITICAL. Pass/Fail: Is the tech debt backlog under control (< 10 items, none > 5 sessions old)? Yes = pass. No = fail.

**Gate Candidate**: PARTIAL -- Session-start check. MCP session_focus loads tech debt count. Advisory warning if > 10 items or any item > 5 sessions old.

---

## A-3H: Head / Heart / Hands Framework

**Original Principle**:
- **Head**: Cultivate customer-first mindset. Share customer insights/feedback/stories with team.
- **Heart**: Create emotional connection to customer needs. Empathize. Feel ownership.
- **Hands**: Translate into tangible actions. Customer-centric KPIs.

**Software Translation**: Every decision-maker (human or AI) must operate with customer understanding (Head), customer empathy (Heart), and customer-measurable actions (Hands). The system must understand who the customer is, care about their experience, and verify outcomes with customer-facing metrics.

**DO THIS**:
1. **Head**: At session start, state the customer persona and their current pain point.
2. **Heart**: When evaluating tradeoffs, apply the 4 Perspectives (Parent/Teacher/Operator/Creator).
3. **Hands**: Every session must advance at least one item in PRODUCT_ACCEPTANCE_TESTS.yaml.

**DON'T DO THIS**:
1. Operate for an entire session without referencing the customer once.
2. Optimize internal metrics (test counts, governance scores) without checking if the customer experience improved.
3. Build features that sound impressive in a spec but that no customer asked for or would notice.

**Measurement**: Session retrospective includes "customer impact" field. If empty for 3+ consecutive sessions, the principle is violated. Pass/Fail: Did this session make the product measurably better for a customer? Yes = pass. No = fail.

**Gate Candidate**: YES -- Session-end retrospective hook. Prompt hook checks retrospective output for customer impact field. Advisory WARN if missing.

---

# PART 2: NIKE 11 MAXIMS

---

## N1: It Is Our Nature to Innovate

**Original Principle**: "Innovation is a core competency, not just a goal."

**Software Translation**: Innovation means solving problems in ways that create defensible advantages -- proprietary algorithms, unique data pipelines, architectural moats. Not just adding more features.

**DO THIS**:
1. Identify and protect the proprietary IP per product (DingDawg: AI ordering + business intelligence; PS: 3-Question Buffer + adaptive curriculum; Agent 1: MiLA governance + credential vault).
2. When building a feature, ask: "Does this create a moat or just match the competition?" Prioritize moat-building.
3. Invest in capabilities competitors cannot easily replicate.

**DON'T DO THIS**:
1. Copy competitor features without understanding why they built them.
2. Open-source proprietary differentiators (full MiLA SEK, payment engine, credential vault).
3. Build generic solutions when a domain-specific innovation would create a lasting advantage.

**Measurement**: Each product has a documented "moat inventory" (3+ features competitors cannot easily replicate). Pass/Fail: Can you name 3 defensible innovations per product right now? Yes = pass. No = fail.

**Gate Candidate**: NO -- Strategic, not automatable. Reviewed during quarterly planning.

---

## N2: Nike Is a Company

**Original Principle**: "Focus on acquiring/pursuing opportunities that serve human potential."

**Software Translation**: Build products that make people's lives genuinely better, not just technically impressive. The company exists to serve human needs, not to demonstrate engineering prowess.

**DO THIS**:
1. Frame every product around its job-to-be-done: DingDawg = "I'm hungry, get me food with no surprises." PS = "I want my child educated without me being a teacher." Agent 1 = "Handle boring tasks so I can focus."
2. Kill features that do not serve the JTBD, even if technically impressive.
3. Prioritize user empowerment over user dependence.

**DON'T DO THIS**:
1. Build features that serve the developer's curiosity but not the user's need.
2. Pursue technical complexity for its own sake (59 hooks serving no customer outcome).
3. Forget that the products exist to make money by solving real problems for real people.

**Measurement**: Every feature in the product backlog has a JTBD tag. Features without JTBD tags are deprioritized. Pass/Fail: Can every active feature trace to a job-to-be-done? Yes = pass. No = fail.

**Gate Candidate**: PARTIAL -- Backlog hygiene check at session start. Advisory only.

---

## N3: Nike Is a Brand

**Original Principle**: "Only enter markets they believe they can dominate."

**Software Translation**: Do not spread across too many markets. Pick the ones where you can be clearly the best and dominate those. Half-built features across 10 categories lose to one excellent feature in 3 categories.

**DO THIS**:
1. Each product targets a specific market segment: DingDawg = small/medium restaurants; PS = homeschool families; Agent 1 = AI-powered task automation.
2. Before adding a new market segment, prove the existing ones are profitable first.
3. Build for minimum lovable product (MLP), not minimum viable product (MVP).

**DON'T DO THIS**:
1. Try to serve enterprise, SMB, and consumer simultaneously before being profitable in any single segment.
2. Add feature categories (analytics, CRM, social) before the core flow is delightful.
3. Launch in a market you cannot commit to dominating within 12 months.

**Measurement**: Each product has ONE primary market segment. Revenue from that segment is tracked separately. Pass/Fail: Is the primary segment defined and is progress toward dominance measurable? Yes = pass. No = fail.

**Gate Candidate**: NO -- Strategic decision. Tracked in domain kernel docs.

---

## N4: Simplify and Go

**Original Principle**: "Decisions must be fast and skillful. Short life-cycles demand speed."

**Software Translation**: Ship fast, iterate fast. The cost of not shipping (zero customer feedback, zero revenue) exceeds the cost of shipping something imperfect. Analysis paralysis is the enemy.

**DO THIS**:
1. Set a ship-it deadline for every major feature. Cut scope to meet it -- never extend the deadline.
2. Make architectural decisions in under 1 session. If it takes longer, the decision is too big -- break it down.
3. 80/20 rule: 80% of value from 20% of features. Ship the 20% first.

**DON'T DO THIS**:
1. Spend 50+ sessions without deploying to production.
2. Refactor working code to make it "cleaner" before a single customer has used it.
3. Build comprehensive error handling for impossible edge cases before the happy path works.

**Measurement**: Sessions since last production deployment. Pass/Fail: Has the product been deployed in the last 10 sessions? Yes = pass. No = fail.

**Gate Candidate**: YES -- Session-start check. MCP audit_record query for last deployment event. Advisory CRITICAL warning if > 10 sessions since last deployment.

---

## N5: The Consumer Decides

**Original Principle**: "Consumer is ultimate stakeholder. Focus on practical AND emotional needs."

**Software Translation**: Internal quality metrics (test counts, governance scores, code coverage) are irrelevant if the consumer cannot complete their task. The consumer's experience is the only metric that cannot be gamed.

**DO THIS**:
1. Run a full E2E user journey walkthrough at least once every 3 sessions.
2. Track un-gameable metrics: "Can a customer complete an order?" "Did money change hands?" "Did the customer return?"
3. When internal metrics conflict with customer experience, customer experience wins.

**DON'T DO THIS**:
1. Declare "production ready" based on test counts or governance scores alone.
2. Optimize proxy metrics (hook count, audit entries) over real metrics (customer completion rate, revenue).
3. Skip the E2E walkthrough because "all tests pass."

**Measurement**: E2E user journey walkthrough completed within last 3 sessions. All acceptance test journeys pass with real HTTP requests. Pass/Fail: Has a real user journey been verified in the last 3 sessions? Yes = pass. No = fail.

**Gate Candidate**: YES -- Session-end gate. HARD BLOCK on new feature work until E2E walkthrough is completed if > 3 sessions overdue.

---

## N6: Be a Sponge

**Original Principle**: "Stay curious. Look for 'diamonds in the dirt.'"

**Software Translation**: Continuously learn from competitors, open-source projects, user feedback, and failures. Every bug, failed agent, and user complaint is data. Extract the lesson and encode it structurally.

**DO THIS**:
1. After every failure, append a 1-line lesson to memory/lessons.md with date, category, and what was learned.
2. When a bug is fixed in one product, check if the same pattern exists in the other products.
3. Read competitor products and industry research at least once per quarter.

**DON'T DO THIS**:
1. Repeat the same mistake without checking lessons.md first.
2. Fix a bug in DingDawg without checking if the same pattern exists in Project School or Agent 1.
3. Treat failures as embarrassments rather than data.

**Measurement**: lessons.md grows by at least 3 entries per session. Recurring themes (same category, 3+ entries) have structural fixes proposed. Pass/Fail: Did this session produce at least 1 new lesson? Yes = pass. No = fail.

**Gate Candidate**: YES -- Session-end check. MCP lesson_correlate detects recurring themes. Advisory WARN if same category has 3+ lessons without a structural fix.

---

## N7: Evolve Immediately

**Original Principle**: "Embrace perpetual change as source of innovation."

**Software Translation**: When a better approach is discovered, implement it immediately. The cost of carrying outdated patterns increases every session they persist.

**DO THIS**:
1. When a better pattern is discovered during work, refactor in the same session (if < 5 files).
2. Track methodology rules as temporary debt -- every text rule should have a plan for structural replacement.
3. Sunset governance tools that have not prevented a real incident in 10 sessions.

**DON'T DO THIS**:
1. Keep using a deprecated pattern "because it works" when a better one exists.
2. Let the rule/hook count grow monotonically without sunsetting unused ones (one-in-one-out policy).
3. Defer improvements to "next session" repeatedly.

**Measurement**: Rule/hook count tracked per session. If count increased without a corresponding sunset, flag it. Pass/Fail: Is the complexity count (hooks + rules + protocols) stable or decreasing? Yes = pass. No = fail.

**Gate Candidate**: PARTIAL -- MCP registry_check tracks feature count. Advisory WARN if count exceeds threshold without sunset documentation.

---

## N8: Do the Right Thing

**Original Principle**: "Transparency, diversity, sustainability."

**Software Translation**: Security is never tech debt. Privacy is never a nice-to-have. Accessibility is never optional. These are baseline requirements, not features.

**DO THIS**:
1. Security stubs, missing auth headers, unguarded endpoints = P1 always, same priority as ship-blockers.
2. Every user data operation follows privacy-by-default (collect minimum data, encrypt at rest, honor deletion requests).
3. Fail-closed on every error handler. Never silently continue when something goes wrong.

**DON'T DO THIS**:
1. Ship known security vulnerabilities to "fix later."
2. Log PII, credentials, or API keys to console, files, or audit trails.
3. Skip accessibility because "we'll add it later."

**Measurement**: Zero P1 security issues in backlog. Security scan runs on every release. Pass/Fail: Are there any open P1 security issues? If yes = fail.

**Gate Candidate**: YES -- CI gate. mila_sentinel_scan on every PR/deployment. HARD BLOCK if any HIGH/CRITICAL findings.

---

## N9: Master the Fundamentals

**Original Principle**: "Continuous refinement of process for elite performance."

**Software Translation**: Get the basics right before optimizing. Auth works. Payments work. Data persists. Errors are handled. The fundamentals must be flawless before advanced features.

**DO THIS**:
1. Before any session of feature work, verify fundamentals: health endpoint returns 200, auth flow works, core CRUD operations succeed.
2. Maintain a "fundamentals checklist" per product verified every 5 sessions.
3. When a fundamental breaks, it becomes P0 regardless of what else is in progress.

**DON'T DO THIS**:
1. Build advanced features on top of broken fundamentals.
2. Skip the smoke test because "nothing changed."
3. Declare a feature "done" when the underlying fundamental it depends on is broken.

**Measurement**: Smoke test (health, auth, core CRUD) passes every session. Pass/Fail: Does the smoke test pass right now? Yes = pass. No = fail.

**Gate Candidate**: YES -- Session-start hook. Run health endpoint + auth smoke test at session start. Advisory WARN on failure. Promotable to HARD BLOCK.

---

## N10: We Are on the Offense -- Always

**Original Principle**: "Aggressive, leader-focused mindset to stay ahead."

**Software Translation**: Ship before competitors. Launch before you are "ready." A deployed product with known limitations beats an undeployed product with 913 tests. Offense means putting product in front of users.

**DO THIS**:
1. Deploy to staging/production at least once every 10 sessions.
2. Set aggressive but achievable deadlines: MVP in 4 weeks, V1 in 8 weeks.
3. When in doubt between "ship with limitation" and "wait until perfect," choose ship.

**DON'T DO THIS**:
1. Wait for "just one more feature" before deploying -- perfectionism drift.
2. Spend more sessions on internal tooling than on customer-facing product (pre-launch: max 20% on tooling).
3. Let the standard for "ready" increase continuously -- lock the MVP definition and cut scope.

**Measurement**: Deployment frequency: at least 1 per 10 sessions. Infrastructure-to-product ratio: <= 20% pre-launch. Pass/Fail: Have we deployed in the last 10 sessions? Yes = pass. No = fail.

**Gate Candidate**: YES -- Same gate as N4. MCP audit_record tracks deployment events.

---

## N11: Remember the Man

**Original Principle**: "Tribute to Bowerman: spirit of innovation + understanding athlete needs."

**Software Translation**: Remember WHY you are building. The user is a real person. DingDawg: a hungry person. PS: a parent wanting the best for their child. Agent 1: a person drowning in tasks. Never lose sight of the human.

**DO THIS**:
1. Keep the JTBD for each product visible in every session handoff document.
2. When making tradeoff decisions, ask: "What would the user want?" not "What is technically elegant?"
3. Celebrate shipping to real users as the primary success metric.

**DON'T DO THIS**:
1. Lose the human in the architecture.
2. Optimize for developer convenience at the expense of user experience.
3. Forget that behind every order is a hungry person, behind every lesson is a child.

**Measurement**: Every product has a visible JTBD statement in its domain kernel or session handoff. Pass/Fail: Can you state the JTBD for the active product without looking it up? Yes = pass. No = fail.

**Gate Candidate**: NO -- Mindset principle. Reinforced by PERMANENT RULE #8 (4 Perspectives).

---

# PART 3: MUSK 5 OPERATIONAL PRINCIPLES

---

## M1: Promote the Vision

**Original Principle**: "Sell a futuristic 'leap of faith' (Mars colonization) to keep investors/employees focused on long-term goals."

**Software Translation**: Every product needs a compelling vision larger than the current state. The vision keeps the team focused when daily work gets grinding. It must be concrete enough to measure progress against.

**DO THIS**:
1. Each product has a "press release" (Amazon Working Backwards format): customer problem, solution, customer quote, how to get started, why it matters.
2. Every session measures distance to the press release.
3. The vision is referenced in every session handoff to prevent drift.

**DON'T DO THIS**:
1. Build without a clear end-state vision ("we're building a food delivery app" is not a vision).
2. Let daily tactical work obscure the strategic goal.
3. Change the vision every session -- vision is stable, tactics adapt.

**Measurement**: Press release exists per product and is referenced in session handoffs. Pass/Fail: Does the press release exist and has it been referenced in the last 5 sessions? Yes = pass. No = fail.

**Gate Candidate**: PARTIAL -- Session handoff template includes "vision alignment" field. Advisory WARN if empty.

---

## M2: Continuous Innovation

**Original Principle**: "Maintain mantra that revolutionary products are always 'almost here.'"

**Software Translation**: Always have a "next big thing" in the pipeline. Continuous improvement is a feature, not a phase.

**DO THIS**:
1. Maintain a "next release" plan that is always 1-2 sessions away from shipping something tangible.
2. After every deployment, immediately define the next improvement cycle.
3. Communicate progress regularly: "Here is what shipped, here is what is next."

**DON'T DO THIS**:
1. Treat deployment as the finish line. Deployment is the starting line for the next iteration.
2. Let the "next big thing" be perpetually 10 sessions away.
3. Spend more time planning the next thing than shipping the current thing.

**Measurement**: There is always a defined "next release" with a target session number. Gap between current session and target <= 5 sessions. Pass/Fail: Is there a defined next release within 5 sessions? Yes = pass. No = fail.

**Gate Candidate**: PARTIAL -- Session focus tracks "next release target." Advisory WARN if no target defined or > 5 sessions away.

---

## M3: Control the Process

**Original Principle**: "Prefer vertical integration. SpaceX makes 70% of components in-house to control own destiny."

**Software Translation**: Own the critical path. Do not depend on external services for core functionality where failure would be catastrophic. Build in-house what must be reliable; use third parties for commodity functionality.

**DO THIS**:
1. Own auth, core business logic, data storage, and the governance layer.
2. Use third-party services for commodity: payments (Stripe), email (SendGrid), hosting (Railway/Fly.io).
3. For every third-party dependency, have a documented fallback or migration plan.

**DON'T DO THIS**:
1. Depend on a single vendor for core functionality without a migration plan.
2. Use a third-party service for a competitive differentiator.
3. Add dependencies without justification. Every new pip/npm package is a risk surface.

**Measurement**: Every critical-path component is owned or has a migration plan. New dependencies require justification. Pass/Fail: Can you name the fallback for every third-party service? Yes = pass. No = fail.

**Gate Candidate**: PARTIAL -- CI check counts new dependencies per PR. Advisory WARN if > 3 new dependencies without justification.

---

## M4: The "Idiot Index"

**Original Principle**: "Measure cost of finished part vs raw materials. Engineers must push this number DOWN. Ruthless cost discipline."

**Software Translation**: Measure the ratio of effort spent to value delivered. A feature that takes 10 sessions to build and is used by 0 customers has an infinite idiot index. Minimize effort per unit of customer value.

**DO THIS**:
1. Track "sessions to ship" for every feature. Investigate any feature that takes > 5 sessions.
2. Measure tokens-per-customer-value: how many tokens to ship something a customer can use?
3. Prefer simple solutions that ship fast over complex solutions that ship never.

**DON'T DO THIS**:
1. Spend 50+ sessions on a product with 0 deployments (infinite cost, zero output).
2. Build a 1000-line governance framework when a 50-line middleware achieves the same protection.
3. Launch 15 agents for work that 1 agent could complete.

**Measurement**: Features shipped / sessions spent. Target: at least 1 customer-visible improvement per 3 sessions. Pass/Fail: Has a customer-visible improvement shipped in the last 3 sessions? Yes = pass. No = fail.

**Gate Candidate**: YES -- MCP session_metrics tracks tasks_completed and agents_launched. Productivity score computed automatically. Advisory WARN if below historical average.

---

## M5: "If a Timeline Is Long, It's Wrong"

**Original Principle**: "Reject initial estimates for costs/schedules. Cut drastically to FORCE innovation."

**Software Translation**: When the estimate is "10 sessions," ask "how do we do it in 3?" Aggressive timelines force creative solutions: simpler architectures, fewer features, tighter scope.

**DO THIS**:
1. For every feature estimate, apply a 50% cut. If estimated at 6 sessions, target 3.
2. Use time-boxing: fixed session budget per feature. When budget is spent, ship what exists.
3. Ship the smallest useful version first. Iterate based on real usage.

**DON'T DO THIS**:
1. Accept long timelines without questioning them.
2. Expand scope to fill available time (Parkinson's Law).
3. Delay shipping to add "one more thing."

**Measurement**: Original estimate vs actual delivery time. Target: features ship within 1.5x original estimate. Pass/Fail: Did the feature ship within 1.5x the estimate? Yes = pass. No = fail.

**Gate Candidate**: PARTIAL -- Session focus tracks estimated vs actual session counts. Advisory WARN if feature exceeds 2x estimate.

---

# PART 4: PROTOCOL FAILURE TERMS -- 11 EXECUTABLE DEFINITIONS

Source: RESEARCH_WHY_PROTOCOLS_FAIL.md. Each term had a gap between what the user means and what the AI system does. The executable definition closes that gap.

---

## T1: "Senior Dev Approved"

**Original Term**: Used to describe code quality standard.

**What User Means**: A 10+ year engineer reviewed this and would stake their reputation on it working in production.

**What AI Does (Wrong)**: Checks syntax, edge cases, error messages, security -- CODE properties, never PRODUCT behavior.

**Executable Definition**: Code passes PRODUCT_ACCEPTANCE_TESTS.yaml user journeys with real HTTP requests. Not just "code looks good" but "customer can use it."

**DO THIS**:
1. Run the relevant acceptance test journey with real HTTP requests before declaring a feature complete.
2. Verify the feature works as a USER would use it (browser/API client), not just as a DEVELOPER tests it (pytest).
3. Check runtime behavior: does the response contain expected data? Does the UI update? Does state persist on refresh?

**DON'T DO THIS**:
1. Declare "senior dev approved" based solely on syntax verification and test counts.
2. Skip the acceptance journey because "all unit tests pass."
3. Self-assess quality without running the actual product.

**Measurement**: Relevant acceptance test journey from PRODUCT_ACCEPTANCE_TESTS.yaml passes with real HTTP requests. Pass/Fail: Does the acceptance journey pass? Yes = pass. No = fail.

**Gate Candidate**: YES -- CI gate. Acceptance test suite runs on every deployment-candidate branch. HARD BLOCK if any journey fails.

---

## T2: "No Vibe Coding"

**Original Term**: Used to describe coding discipline.

**What User Means**: Every line written with full understanding of runtime context, data flow, failure modes.

**What AI Does (Wrong)**: Checks for `pass`, `TODO`, syntax validity -- ARTIFACTS of stubs, not understanding.

**Executable Definition**: Before modifying code, the developer/agent can state the call chain (user action to database and back) AND the data types at each boundary.

**DO THIS**:
1. Before modifying code, trace the call chain: user action -> component -> API call -> route handler -> service -> database -> response -> component update.
2. Verify data types at each boundary (what goes in, what comes out, what happens on error).
3. After modification, verify the entire chain still works with a real request.

**DON'T DO THIS**:
1. Modify code in isolation without understanding how it connects to the rest of the system.
2. Pattern-match for `pass`/`TODO` and declare "no vibe coding" -- semantic stubs are worse than syntactic stubs.
3. Write code based on what "seems right" without reading the existing implementation first.

**Measurement**: Agent can state the call chain for the code being modified. Post-modification, the full chain is verified with a real request. Pass/Fail: Can you trace from user action to database and back? Yes = pass. No = fail.

**Gate Candidate**: YES -- Prompt hook on agent launch. Haiku checks if agent prompt includes a call-chain trace. Advisory WARN if missing for code modification tasks.

---

## T3: "Production Ready"

**Original Term**: Used to describe deployment readiness.

**What User Means**: A paying customer can use this RIGHT NOW.

**What AI Does (Wrong)**: Measures test count, code quality, governance score -- INTERNAL metrics, not external reality.

**Executable Definition**: A deployment smoke test runs the actual application and verifies a user can complete the core flow (signup -> core action -> success confirmation).

**DO THIS**:
1. Run a deployment smoke test that exercises the real application (not mocks, not stubs, not fixtures).
2. Verify the core user flow end-to-end: sign up, perform primary action, see success confirmation.
3. Verify operational readiness: health endpoint with dependency status, monitoring, rollback capability.

**DON'T DO THIS**:
1. Claim "production ready" based on test counts or governance scores.
2. Self-assess production readiness without running the actual application.
3. Use internal quality metrics as a proxy for customer experience.

**Measurement**: Deployment smoke test passes (real app, real requests, core flow complete). Health endpoint returns 200 with dependency status. Pass/Fail: Can a stranger use this product right now without help? Yes = pass. No = fail.

**Gate Candidate**: YES -- CI/CD gate. Smoke test as final step of deployment pipeline. HARD BLOCK if smoke test fails.

---

## T4: "Enterprise Ready"

**Original Term**: Used to describe business trust readiness.

**What User Means**: A business trusts this with their operations -- real RBAC, real data isolation, real monitoring.

**What AI Does (Wrong)**: Checks if enterprise PATTERNS exist in code, not if they WORK in practice.

**Executable Definition**: RBAC integration test suite with real HTTP requests from different user roles verifies tier isolation, role-based access, and data isolation all function correctly.

**DO THIS**:
1. Run RBAC integration tests with real HTTP requests: Customer token cannot access Business endpoints, Business token cannot access Admin endpoints.
2. Verify data isolation: Business A cannot see Business B's data with a valid Business-tier token.
3. Test operational stack: monitoring shows real metrics, alerting fires on 5xx spikes, rollback works within 5 minutes.

**DON'T DO THIS**:
1. Check for RBAC code patterns without verifying they block unauthorized access.
2. Declare "enterprise ready" without testing multi-tenant data isolation.
3. Skip operational readiness verification.

**Measurement**: RBAC integration tests pass with real HTTP requests. Data isolation verified across tenant boundaries. Pass/Fail: Can one tenant access another tenant's data? If yes = fail. Does RBAC block unauthorized access? If no = fail.

**Gate Candidate**: YES -- CI gate. RBAC integration test suite on deployment. HARD BLOCK if cross-tenant leak or unauthorized access succeeds.

---

## T5: "End in Mind" (Covey Habit 2)

**Original Term**: Used to describe goal alignment.

**What User Means**: Every decision traces back to "10,000 families x $99/mo" or "100 restaurants processing orders."

**What AI Does (Wrong)**: Defines success at TASK level ("tests pass") not PRODUCT level ("customer can order food").

**Executable Definition**: A per-product DONE definition exists and is referenced at session start. Every task traces to a line in this definition.

**DO THIS**:
1. Each product has a PRODUCT_DONE_DEFINITION that states what "done" looks like in customer terms.
2. At session start, reference the done definition and select tasks that advance toward it.
3. At session end, measure: "Are we closer to DONE than when we started?"

**DON'T DO THIS**:
1. Define success at the task level without connecting to the product level.
2. Work on tasks that do not advance the done definition without explicit justification.
3. Let the done definition drift.

**Measurement**: PRODUCT_DONE_DEFINITION exists per product. Session start references it. Session end measures distance. Pass/Fail: Can you state the product done definition without looking it up? Yes = pass. No = fail.

**Gate Candidate**: YES -- Session-start hook. MCP session_focus loads done definition. Advisory WARN if session objectives do not align.

---

## T6: "First Things First" (Covey Habit 3)

**Original Term**: Used to describe prioritization.

**What User Means**: Work on what is blocking a paying customer. Nothing else.

**What AI Does (Wrong)**: Has P0-P4 triage but no enforcement. Spends 8 sessions on governance while P0 blockers persist.

**Executable Definition**: A P0 Blocker Gate blocks all non-P0 work when any P0 customer blocker exists.

**DO THIS**:
1. At session start, check for P0 blockers (items preventing a customer from completing the core flow).
2. If P0 blockers exist, work ONLY on P0 items until resolved.
3. Governance, infrastructure, and optimization work is BLOCKED while P0 blockers remain.

**DON'T DO THIS**:
1. Work on governance improvements while the checkout flow is broken.
2. Write more tests while the core user journey cannot complete.
3. Optimize performance while the product cannot be deployed.

**Measurement**: P0 blocker count at session start and end. If P0 blockers existed and non-P0 work was performed, the principle is violated. Pass/Fail: Are there P0 blockers AND was non-P0 work done? If yes = fail.

**Gate Candidate**: YES -- Session-start gate. HARD BLOCK on non-P0 work if any P0 blocker exists. Highest-impact structural enforcement available.

---

## T7: "No Drift"

**Original Term**: Used to describe scope discipline.

**What User Means**: If the session goal is "deploy," every action advances deployment.

**What AI Does (Wrong)**: CUSUM detects QUALITY drift, not SCOPE drift. Session can have perfect metrics while making zero progress.

**Executable Definition**: Objective alignment check every 10 tool calls comparing current work to session objectives.

**DO THIS**:
1. At session start, set clear objectives in session_focus.
2. Every 10 tool calls, verify: "Is my current action advancing the session objectives?"
3. If drifted, STOP and course-correct or explicitly update objectives with justification.

**DON'T DO THIS**:
1. Start working on "something interesting" tangential to the session goal.
2. Let quality metrics substitute for scope tracking.
3. Discover at session end that 80% of work was unplanned.

**Measurement**: Percentage of session tool calls advancing stated objectives. Target: >= 80%. Pass/Fail: Were session objectives achieved? Yes = pass. No = fail.

**Gate Candidate**: YES -- Turn counter hook (protocol-reminder.sh) fires at turns 20, 30, 40+. Enhancement: add objective alignment check to hook output.

---

## T8: "No Hallucinations"

**Original Term**: Used to describe truthfulness.

**What User Means**: If the system says "9/10 production ready," the product is actually deployable.

**What AI Does (Wrong)**: Catches FACTUAL hallucinations but not EVALUATIVE ones ("this is enterprise ready" when it is not).

**Executable Definition**: Evaluative claims require executable evidence. Any quality rating must be backed by a specific passing test or verification.

**DO THIS**:
1. Every quality claim must include evidence: which test passed, which endpoint returned 200, which user flow completed.
2. Use the 3-strike system: first unverified claim = warning, second = audit record, third = hard block requiring evidence.
3. Distinguish between factual claims ("200 lines") and evaluative claims ("production ready"). Evaluative claims need higher evidence.

**DON'T DO THIS**:
1. Declare "production ready 9/10" without listing the 1/10 gap AND evidence for the 9/10.
2. Self-assess quality without running verification.
3. Use qualitative language ("robust," "comprehensive") without quantitative backing.

**Measurement**: Every quality claim includes linked evidence. Claims without evidence are flagged. Pass/Fail: Is every quality claim backed by executable evidence? Yes = pass. No = fail.

**Gate Candidate**: YES -- task-completed-proof-gate.sh hook (advisory). Promote to hard block for evaluative claims.

---

## T9: "No Stubs"

**Original Term**: Used to describe implementation completeness.

**What User Means**: Every function does what it claims. "process_payment" actually processes payments.

**What AI Does (Wrong)**: Pattern-matches for `pass`, `TODO`, `NotImplementedError` -- misses SEMANTIC stubs that return success without doing anything.

**Executable Definition**: Behavioral verification -- call every endpoint, verify side effects occur (database writes, external API calls, state changes).

**DO THIS**:
1. For every endpoint that claims to DO something, verify the side effect occurred (check database, external service, state).
2. Test with behavioral assertions: not just "returns 200" but "returns 200 AND the order appears in the database AND status is CONFIRMED."
3. Grep for semantic stub patterns: functions that return success without database writes, API calls, or state mutations.

**DON'T DO THIS**:
1. Accept "returns 200" as proof that a function works (it might return 200 without doing anything).
2. Pattern-match only for syntactic stubs and miss semantic stubs.
3. Trust function names as documentation of behavior.

**Measurement**: For every state-changing endpoint, at least one test verifies the side effect. Pass/Fail: Does every "action" endpoint have a side-effect verification test? Yes = pass. No = fail.

**Gate Candidate**: YES -- CI gate. Behavioral test suite verifies side effects for all state-changing endpoints. Advisory WARN if an endpoint lacks a side-effect test.

---

## T10: "Commercially Ready"

**Original Term**: Used to describe market readiness.

**What User Means**: Someone would pay money because it solves their problem better than alternatives.

**What AI Does (Wrong)**: Tracks test counts and governance scores. Has zero tools for business validation.

**Executable Definition**: Customer simulation test -- scripted walkthrough of the entire customer experience from discovery to payment to repeated use.

**DO THIS**:
1. Run a customer simulation: pretend you are the target customer, walk through the entire experience from landing page to payment to receiving value.
2. Identify every friction point, confusing label, and missing feature that would prevent a real purchase.
3. Compare against alternatives: would the target customer choose this over existing options?

**DON'T DO THIS**:
1. Declare "commercially ready" without simulating the full purchase experience.
2. Ignore competitive alternatives.
3. Confuse "code complete" with "commercially ready."

**Measurement**: Full customer simulation walkthrough documented with friction points. Competitive comparison on file. Pass/Fail: Would YOU pay for this product right now? If not, what is missing? Honest answer required.

**Gate Candidate**: PARTIAL -- MCP audit_record tracks "customer_simulation" events. Advisory WARN if no simulation in last 5 sessions.

---

## T11: "Human Performance Optimizer"

**Original Term**: Used to describe AI effectiveness.

**What User Means**: AI makes the human MORE effective. Every hour in Claude Code produces more value than an hour without it.

**What AI Does (Wrong)**: Optimizes AI throughput (tokens, agents, tasks). Does not track human effort managing the AI.

**Executable Definition**: Track human_interventions as a negative metric. Optimize value_delivered / human_effort. Every time the user has to remind, correct, or repeat instructions, that is a failure.

**DO THIS**:
1. Track "human interventions per session" -- every reminder, correction, or re-explanation is a negative metric.
2. Optimize for user-hours-saved, not tokens-consumed.
3. Automate repetitive user actions: if the user has reminded about the same thing 3 times, make it a hook/rule/structural enforcement.

**DON'T DO THIS**:
1. Optimize AI throughput (more agents, more tokens) while the user spends more time managing the AI.
2. Require the user to paste context, remind about rules, or re-explain priorities that should be persistent.
3. Celebrate high token consumption as productivity when the user is spending more time supervising.

**Measurement**: Human interventions per session. Target: decreasing trend. Pass/Fail: Did the user have to remind the AI about something it should already know? If yes = fail for that item.

**Gate Candidate**: YES -- MCP audit_record tracks "human_intervention" events. Trend analysis via drift_detect. Structural fix: convert every repeated intervention into a hook or rule.

---

# APPENDIX: CROSS-REFERENCE MATRIX

| # | Principle | Category | Gate Type | Priority |
|---|-----------|----------|-----------|----------|
| A1 | Innovation Driven by Customer Needs | Amazon | Prompt hook (advisory) | HIGH |
| A2 | Personalization and Convenience | Amazon | CI (Lighthouse) | HIGH |
| A3 | Empowering with Information | Amazon | CI (lint rule) | MEDIUM |
| A4 | Long-Term Thinking | Amazon | Session check (advisory) | MEDIUM |
| A-3H | Head/Heart/Hands | Amazon | Session retrospective | MEDIUM |
| N1 | Innovate | Nike | Strategic review | LOW |
| N2 | Company (Human Potential) | Nike | Backlog check | LOW |
| N3 | Brand (Dominate Market) | Nike | Strategic review | LOW |
| N4 | Simplify and Go | Nike | Session audit (deploy freq) | CRITICAL |
| N5 | Consumer Decides | Nike | Session gate (E2E walkthrough) | CRITICAL |
| N6 | Be a Sponge | Nike | Session check (lessons.md) | MEDIUM |
| N7 | Evolve Immediately | Nike | Registry check (sunset) | MEDIUM |
| N8 | Do the Right Thing | Nike | CI (security scan) | CRITICAL |
| N9 | Master Fundamentals | Nike | Session hook (smoke test) | HIGH |
| N10 | On the Offense | Nike | Session audit (deploy freq) | CRITICAL |
| N11 | Remember the Man | Nike | JTBD in domain kernel | LOW |
| M1 | Promote the Vision | Musk | Session handoff template | MEDIUM |
| M2 | Continuous Innovation | Musk | Session focus (next release) | MEDIUM |
| M3 | Control the Process | Musk | CI (dependency audit) | HIGH |
| M4 | Idiot Index | Musk | MCP session_metrics | HIGH |
| M5 | Timeline Is Wrong | Musk | Session focus (estimate tracking) | HIGH |
| T1 | Senior Dev Approved | Term | CI (acceptance tests) | CRITICAL |
| T2 | No Vibe Coding | Term | Prompt hook (call chain) | HIGH |
| T3 | Production Ready | Term | CI (smoke test) | CRITICAL |
| T4 | Enterprise Ready | Term | CI (RBAC integration) | CRITICAL |
| T5 | End in Mind | Term | Session hook (done definition) | HIGH |
| T6 | First Things First | Term | Session gate (P0 blocker) | CRITICAL |
| T7 | No Drift | Term | Turn counter hook | HIGH |
| T8 | No Hallucinations | Term | Proof gate hook | HIGH |
| T9 | No Stubs | Term | CI (behavioral tests) | HIGH |
| T10 | Commercially Ready | Term | Session audit (simulation) | MEDIUM |
| T11 | Human Performance Optimizer | Term | MCP audit (interventions) | HIGH |

---

# APPENDIX: 8 ANTI-PATTERNS

Source: RESEARCH_COVEY_ALIGNMENT_ANTIPATTERNS.md

| # | Anti-Pattern | Detection | Prevention | Pass/Fail Test |
|---|-------------|-----------|------------|----------------|
| 1 | Governance Theater | Zero incidents prevented in 10 sessions | Sunset clause: 10-session review, remove if unused | Has this gate prevented a real incident? If no for 10 sessions = fail |
| 2 | Test-Count Theater | E2E walkthrough finds bugs tests miss | E2E-First Gate: session requires user flow pass | Did E2E find bugs that unit tests missed? If yes = test theater detected |
| 3 | Means-End Inversion | 3+ internal-majority sessions | Press Release Test: advance the press release | Are tools serving the product or has the tool become the product? |
| 4 | Local Optimization | Component avg > system score by 3+ | System-level smoke test as primary metric | Does the product work end-to-end despite components scoring well? |
| 5 | Perfectionism Drift | 10+ sessions since deployment | Ship-It Deadline: fixed date, scope cuts | Sessions since deployment > 10? If yes = fail |
| 6 | Vocabulary Without Substance | Quality claims without evidence | Definition-of-Done per term (this document) | Is every quality claim backed by evidence? If no = fail |
| 7 | Complexity Ratchet | Rule/hook count only increases | One-In-One-Out. Complexity budget. Sunset reviews. | Did complexity increase this session without a corresponding sunset? |
| 8 | Infrastructure Addiction | Infrastructure > 40% of sessions | Product-First: every session starts with product work | Was more than 40% of the last 10 sessions spent on infrastructure? |

---

# APPENDIX: THREE LAWS OF COMMERCIAL READINESS

Source: RESEARCH_PRODUCT_QUALITY_STANDARDS.md

**LAW 1**: A product is not ready until a STRANGER can use it without help.
- Test: Give the URL to someone who has never seen the product. Can they complete the core flow? Pass/Fail.

**LAW 2**: What users cannot perceive does not exist.
- Test: 913 tests, 59 hooks, 17 protocols -- does ANY of this appear in the user experience? If not, it does not count toward readiness. Pass/Fail.

**LAW 3**: The first 5 minutes determine everything.
- Test: Start a stopwatch. Open the product. Can you understand what it does and begin using it within 5 minutes? Pass/Fail.

---

# APPENDIX: PROXY METRICS vs REAL METRICS

| Proxy (Gameable) | Real (Cannot Game) |
|---|---|
| Test count | Can a customer complete the flow? |
| Governance score | Did money change hands? |
| Production readiness score | Did the customer return? |
| Hook count | Did the user complete onboarding? |
| Agent count | Did customer-visible output increase? |
| Token consumption | Did the user need fewer interventions? |

---

## DOCUMENT METADATA

- **Created**: 2026-02-19 (updated from earlier draft)
- **Source Documents**: 4
  1. `RAW_SOURCE_AMAZON_NIKE_MUSK_PRINCIPLES.md`
  2. `RESEARCH_WHY_PROTOCOLS_FAIL.md`
  3. `RESEARCH_PRODUCT_QUALITY_STANDARDS.md`
  4. `RESEARCH_COVEY_ALIGNMENT_ANTIPATTERNS.md`
- **Principles Covered**: Amazon (4 + 3H = 5 entries), Nike (11), Musk (5), Protocol Failure Terms (11)
- **Total Entries**: 32 principles with DO/DON'T/MEASURE/GATE
- **8 Anti-Patterns**: Detection + Prevention + Pass/Fail
- **3 Laws**: Commercial Readiness with Pass/Fail tests
- **Cross-Reference Matrix**: All 32 entries with category, gate type, and priority
