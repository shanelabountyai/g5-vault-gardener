# LinkedIn drafts — G5·C Vault Gardener

Two drafts in Shane's voice, each built on one decision from `docs/DECISIONS.md`. **Both: Drafted, unposted.** Written 2026-11-24 by an unattended session; edit freely before posting.

Ground rules applied: sample build on synthetic data, not a client result; every project number is from this repo's committed reports or decisions log and is labelled recorded/synthetic; no personal career figures; no former employer named; none of the banned stock phrases.

---

## Draft 1 — the error limit that never tripped (D-25, D-34)

**State: Drafted, unposted.**

I built an agent job that stops itself after 5 errors in an hour. Then I simulated an outage and it never stopped.

The setup: a sample build where three agents tend a notes folder every 15 minutes, on made-up notes and pre-written model answers. A supervisor watches cost and errors and shuts everything down past a limit.

The error limit worked fine at start-up, when 63 notes hit the model at once. But in a normal day, work arrives a note at a time. Each failing note was retried 15 minutes later and parked after 3 tries. So an outage produced a slow drip of errors that never reached 5 inside any hour. The job just sat there, quietly failing, looking healthy.

Nothing was broken. The limit did exactly what I wrote. I had written the wrong question.

The fix was a second rule: if 80% or more of at least 3 attempts in the window fail, stop. Same outage, and now it trips. The normal simulated day still trips zero times.

The lesson I keep relearning: a threshold tuned on the busy hour says nothing about the quiet ones. If you're watching an always-on process, count the share that fails, not just the number.

What's a limit you set once that turned out to be measuring the wrong thing?

#marketingoperations #aiagents #automation #operations

---

## Draft 2 — mistakes on purpose (D-24)

**State: Drafted, unposted.**

The quality report on my latest sample build says tag precision is 0.94. That number is fake, and I made it fake on purpose.

The build is an agent job that tags and links notes. It runs on made-up notes and model answers I wrote by hand, so tests are repeatable and nothing costs money.

Here's the trap. If I'd written perfect answers, the quality report would show 1.00 across the board. It would look great and prove nothing, because a perfect score can't tell you whether the scoring works.

So I wrote mistakes into the answers: a missing status tag, a wrong extra topic, a tag outside the agreed list, a wrong note type, one garbled response, a link to a note that doesn't exist. Then I checked the report caught exactly those, no more and no fewer. It did: 17 of 20 labelled notes pass, and each of the 3 that fail carries one of the mistakes I planted.

The report now proves the measuring works. It still says nothing about how good a real model is. That needs a live run I haven't done yet, and the write-up says so in plain words next to every number.

When a dashboard comes back all green on day one, my first question is whether it could have shown red at all.

How do you test the thing that's supposed to be testing your work?

#marketingoperations #ai #dataquality #measurement

---

## Source check

| Claim in a draft | Source |
|---|---|
| 3 agents, every 15 minutes, made-up notes, pre-written answers | README.md; D-1, D-9 |
| 5 errors in 60 minutes; 63-note start-up backlog; retried 15 min apart, parked after 3 | D-15, D-21, D-25 |
| ≥ 80% of at least 3 attempts → trip; normal day 0 trips | D-34; `docs/daily-report-simulated.md` (Supervisor trips 0) |
| Tag precision 0.9375; 17 of 20 pass | `docs/quality-report.md` (recorded fixtures, synthetic) |
| The list of designed mistakes | D-24 |
| No live run yet | README.md, NEXT.md |
