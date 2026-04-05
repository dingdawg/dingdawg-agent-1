# Project School -- Done Definition (Press Release Format)

**Date:** 2026-02-19 | **Product:** Project School (Homeschool Platform for Families)

---

## The Customer Problem

"I pulled my kids out of school because the system wasn't meeting their needs. But now I'm supposed to be their teacher, and I'm not a teacher. I'm spending 4 hours a day trying to find the right curriculum, create lesson plans, and figure out if my kids are actually learning. I feel guilty when I can't keep up. I want to feel like a good parent, not a failing teacher."

## The Solution

Project School turns homeschooling from a full-time teaching job into a 30-minute daily check-in. The platform handles everything: it assesses each child's level, generates a personalized daily schedule aligned to state standards, delivers age-appropriate lessons, adapts difficulty in real-time using our proprietary 3-Question Buffer, and reports progress to parents in plain English. Parents set goals and monitor progress. The AI does the teaching. Kids learn at their own pace. Everyone wins.

## Customer Quote

"Before Project School, I was spending 3 hours a day pulling together worksheets and trying to explain fractions to my 9-year-old while my 6-year-old destroyed the kitchen. Now my kids open the app, do their lessons, and I get a report that says 'Emma mastered multiplication this week' and 'Jake needs more practice with vowel sounds.' I'm back to being their mom, not their stressed-out substitute teacher." -- Rachel T., Homeschool Mom of 3

## How to Get Started

1. **Sign up** (1 minute) -- Email, password, and your state (for standards alignment).
2. **Add your child** (2 minutes) -- Name, grade level, and any learning accommodations (dyslexia, ADHD, gifted -- all supported).
3. **Start learning** (immediately) -- A placement assessment runs in 5 minutes, then your child's first personalized lesson begins.

Total time from first visit to first lesson: **under 10 minutes**.

## Creator Quote

"Every parent who homeschools chose the harder path because they believe in something better for their child. We built Project School to reward that courage. The AI isn't replacing parents -- it's giving them superpowers. A personalized tutor that never gets tired, never gets frustrated, and adjusts to every child's unique needs. For $99 a month, that's the best education investment a family can make." -- DingDawg Team

---

## Done Criteria (Binary Pass/Fail)

### Parent First-Run (Law 3: First 10 Minutes)
- [ ] Parent can sign up with 3 or fewer fields
- [ ] Onboarding wizard guides through child setup without confusion
- [ ] Curriculum standard selection works (defaults to state standard)
- [ ] Accommodations are collected and clearly optional
- [ ] Child's first lesson begins within 10 minutes of signup
- [ ] Pricing is visible before signup

### Student Daily Experience (Law 2: Core Product Loop)
- [ ] Daily schedule shows today's lessons with subject labels
- [ ] Lesson content loads with topic, explanation, and practice questions
- [ ] Questions are grade-appropriate (not too easy, not too hard)
- [ ] Immediate feedback on answers (correct/incorrect with explanation)
- [ ] Lesson completion shows score and encouraging message
- [ ] Completed lessons marked on schedule, next lesson highlighted
- [ ] 3-Question Buffer adapts difficulty in real-time

### Parent Dashboard (Law 2: Parent Must See Value)
- [ ] Dashboard shows lessons completed, subjects covered, mastery levels
- [ ] Per-subject progress detail available (standards met, areas needing work)
- [ ] Weekly summary report generates automatically
- [ ] Accommodations status visible (what's active, what it affects)
- [ ] Multiple children manageable from single account

### Adaptive Learning (The Moat)
- [ ] Buffer engine adjusts difficulty after 3 correct answers (increase) or 1 incorrect (decrease)
- [ ] Mastery assessment updates after each buffer cycle
- [ ] Student never gets stuck on content that's too hard for more than 2 questions
- [ ] Student never gets bored by content that's too easy for more than 3 questions
- [ ] Scope and sequence follows 40-week curriculum map

### Accommodations (Collected Data Must Work)
- [ ] Dyslexia accommodation: larger text, shorter passages, audio option
- [ ] ADHD accommodation: shorter lessons, more breaks, gamification elements
- [ ] Gifted accommodation: accelerated pacing, enrichment content
- [ ] Accommodation changes are visible to parent AND student
- [ ] Accommodations persist across sessions and devices

### Payment (Revenue Requirement)
- [ ] Pricing page exists with clear monthly/annual options
- [ ] Stripe payment flow works end-to-end
- [ ] Trial period clearly communicated (length, what's included, what happens after)
- [ ] Self-service cancellation in 3 clicks or fewer
- [ ] No payment required for initial placement and first week

### Mobile and PWA (Permanent Rule #14)
- [ ] PWA installable on tablet and phone
- [ ] Tablet-optimized layout (primary device for many homeschool families)
- [ ] No horizontal scroll at 375px
- [ ] Touch targets minimum 44x44px
- [ ] Standalone mode works
- [ ] Offline access to cached lesson content

### Polish (Premium UX)
- [ ] No "undefined", "null", "NaN", or stack traces in UI
- [ ] Custom 404 page
- [ ] Custom error page with helpful message
- [ ] Loading states on all async operations
- [ ] Child-friendly language in student-facing content
- [ ] Empty states with encouraging illustrations
- [ ] Progress animations when completing lessons

### Security and Privacy (Protecting Children's Data)
- [ ] COPPA compliance considerations documented and addressed
- [ ] Parent controls access to child's account
- [ ] Student data not shared with third parties
- [ ] Authentication works (login, logout, token refresh)
- [ ] Data isolation between families

### Operations (Production Readiness)
- [ ] Health endpoint returns 200 with dependency status
- [ ] Content quality gate active (no inappropriate content reaches students)
- [ ] Database has 12,350+ questions covering all grades and subjects
- [ ] Automated daily backups of student progress data
- [ ] Monitoring on error rates and latency

### Performance (Measurable Thresholds)
- [ ] LCP under 2.5 seconds
- [ ] Lesson content loads under 2 seconds
- [ ] Question feedback under 2 seconds
- [ ] API p95 under 500ms
- [ ] Time from signup to first lesson: under 10 minutes

---

## Current Score

**Criteria met: 12 out of 56**

| Category | Passing | Total | Details |
|----------|---------|-------|---------|
| Parent First-Run | 2 | 6 | Onboarding wizard exists, curriculum selection works. Frontend-backend 6 path mismatches. |
| Student Daily | 3 | 7 | 12,350 questions in DB, lesson delivery works, progression chain fixed. Module rendering not fully wired. |
| Parent Dashboard | 1 | 5 | Dashboard exists but progress data pipeline incomplete. |
| Adaptive Learning | 2 | 5 | Buffer engine exists with API endpoints. Full E2E chain unverified. |
| Accommodations | 0 | 5 | Collected but NEVER applied to content delivery. |
| Payment | 0 | 5 | No payment UI, no Stripe integration in frontend. |
| Mobile/PWA | 0 | 6 | No PWA configuration. |
| Polish | 1 | 7 | Some loading states. No custom error pages. |
| Security/Privacy | 2 | 5 | Auth works, family data isolation exists. COPPA not addressed. |
| Operations | 1 | 5 | Content quality gate active, 12,350 questions. No monitoring. |
| Performance | 0 | 5 | Backend is fast but no frontend metrics. |

**Product stage: CODE COMPLETE (backend) / DEMO (full product)** -- Backend is 8.5/10 with strong content. Frontend integration is the critical gap.

**Distance to Done:** 44 criteria remaining. Priority order:
1. Fix frontend-backend wiring (port mismatch, 6 API path mismatches)
2. Verify J002 (student daily lesson) end-to-end in browser
3. Wire accommodations into content delivery (J008)
4. Build payment flow (J005)

The backend is strong. The content is strong. The gap is the LAST MILE -- getting it into the student's hands through a working UI.
