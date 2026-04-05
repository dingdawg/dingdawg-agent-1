# Pre-Deploy Smoke Test Checklist

**Purpose:** Universal smoke test that applies to ALL products before any deployment claim.
**Rule:** If any item fails, the product is NOT ready to deploy. No exceptions. No "we'll fix it after launch."

**The Three Laws (verify before every deploy):**
1. Can a STRANGER use this without help?
2. Does the user PERCEIVE value? (Not "does the backend work?" -- does the USER see it working?)
3. What happens in the FIRST 5 MINUTES? (If it's confusing, they leave. 88% never return.)

---

## Phase 1: Automated Checks (Must All Pass)

### Server Health
- [ ] App starts without errors or manual intervention
- [ ] Health endpoint returns HTTP 200 with dependency status (DB, cache, external services)
- [ ] Database connection established and queries execute
- [ ] No unhandled exceptions in startup logs

### Test Suite
- [ ] All unit tests pass (`pytest` / `npm test`)
- [ ] Zero test failures (not "3 flaky tests we ignore" -- ZERO)
- [ ] Test runtime under 60 seconds (slow tests indicate problems)

### Build
- [ ] Application builds without errors
- [ ] No TypeScript/lint errors in production build
- [ ] Docker image builds successfully (if containerized)
- [ ] Environment variables documented and validated at startup

---

## Phase 2: Manual Verification -- The 5-Minute Test

**Instructions:** Set a timer for 5 minutes. Open the app on a mobile phone (or Chrome DevTools mobile emulation at 375px width). Pretend you have never seen this app before. Complete the core flow.

### Landing Page (30 seconds)
- [ ] Page loads within 3 seconds on mobile
- [ ] Value proposition is clear (what does this app do?) without scrolling
- [ ] Primary CTA (call to action) is visible and obvious
- [ ] No console errors in browser DevTools
- [ ] No layout shift or content jumping as page loads

### Signup/Login (60 seconds)
- [ ] Signup form appears with 3 or fewer fields
- [ ] Form validation shows errors inline (not after submit, not a generic alert)
- [ ] Signup succeeds and redirects to the app
- [ ] Login works for existing users
- [ ] "Forgot password" link exists (even if it's a mailto: for MVP)

### Core Action (120 seconds)
- [ ] The PRIMARY thing this product does can be started within 2 minutes of signup
- [ ] DingDawg Agent 1: Send a message and receive an AI response
- [ ] DingDawg Main (Customer): Browse menu, add to cart, start checkout
- [ ] DingDawg Main (Owner): See dashboard with orders or helpful empty state
- [ ] Project School (Parent): Complete onboarding, see child's first lesson
- [ ] Project School (Student): Open lesson, answer a question, see feedback

### Error Handling (60 seconds)
- [ ] Navigate to a non-existent URL -- see custom 404 page (not browser default)
- [ ] Trigger an error state (disconnect network, submit bad data) -- see human-readable message
- [ ] Error message includes what happened AND what to do next
- [ ] No "undefined", "null", "NaN", "Error", or stack traces visible to user
- [ ] No frozen/unresponsive UI states

### PWA Check (30 seconds)
- [ ] manifest.json loads (check DevTools > Application > Manifest)
- [ ] Service worker registered (check DevTools > Application > Service Workers)
- [ ] "Add to Home Screen" / install prompt available
- [ ] App icons defined (192px and 512px)
- [ ] Theme color set

---

## Phase 3: Performance (Measure, Don't Guess)

### Core Web Vitals (use Chrome DevTools Lighthouse or PageSpeed Insights)
- [ ] LCP (Largest Contentful Paint) under 2.5 seconds
- [ ] INP (Interaction to Next Paint) under 200ms
- [ ] CLS (Cumulative Layout Shift) under 0.1

### Application Performance
- [ ] API responses return within 500ms (p95)
- [ ] Every button gives visual feedback within 100ms (no "dead clicks")
- [ ] No network request failures visible to the user
- [ ] Loading states shown for all async operations (no blank screens while loading)

---

## Phase 4: Security Quick-Check

- [ ] No API keys, tokens, or secrets visible in HTML source
- [ ] No API keys in frontend JavaScript bundles (search for "sk_", "pk_", "api_key")
- [ ] HTTPS enforced (HTTP redirects to HTTPS)
- [ ] Authentication tokens stored securely (httpOnly cookies or secure storage)
- [ ] Accessing other users' data returns 403/404 (not their data)

---

## Phase 5: Mobile Verification

- [ ] No horizontal scrollbar at 375px width
- [ ] All buttons and links have minimum 44x44px touch targets
- [ ] Text is readable without zooming
- [ ] Forms are usable on mobile keyboard (input types correct, no tiny inputs)
- [ ] Navigation works with thumb-only interaction (bottom nav or easy-reach menu)

---

## Scoring

**Pass:** ALL Phase 1 items pass AND all Phase 2 items pass.
**Conditional Pass:** Phase 1 passes, Phase 2 has 1-2 minor failures (cosmetic only, not functional).
**Fail:** Any Phase 1 failure OR any Phase 2 core action failure.

There is no "mostly passes" or "close enough." The product either works for a stranger in 5 minutes, or it does not.

---

## When to Run This Checklist

| Trigger | Required? |
|---------|-----------|
| Before claiming "production ready" | YES -- always |
| Before deploying to any server | YES -- always |
| Before showing to a potential customer | YES -- always |
| After major feature changes | YES -- always |
| After infrastructure changes (DB, hosting) | YES -- always |
| Before updating MEMORY.md production readiness score | YES -- always |
| After writing "9/10 production ready" | YES -- run this FIRST, then see if you still believe that score |

---

## The Meta-Test

After completing this checklist, answer honestly:

**"Would I give this URL to a stranger and bet $100 they could complete the core flow without asking me a single question?"**

If the answer is no, the product is not done. Go back and fix what's broken.
