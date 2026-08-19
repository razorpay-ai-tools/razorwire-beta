# Contributing to Razorwire

Team **Unrealistic Expectations** — Shivang · Sarthak · Saksham · Sambhav

This is a hackathon repo with a feature freeze (`docs/PLAN.md` §7). The point of these
conventions is that four people can work in parallel without stepping on each other,
not process for its own sake.

---

## Contributors

- Shivang
- Sarthak Kapoor
- Saksham Garg — `skshm-grg`
- Sambhav Jain — `sambhavjain2805`

Add yourself when you land your first commit.

---

## Access

The `razorpay-ai-tools` org enforces **SAML SSO**. A brand new clone will fail to push
with a SAML notice even though your credentials are fine. Two things must be true:

1. You have **write** access to the repo.
2. Your SSH key or PAT is **authorized for the org** —
   [github.com/settings/keys](https://github.com/settings/keys) → *Configure SSO* →
   authorize `razorpay-ai-tools`.

A Razorpay security hook also blocks pushes to personal namespaces. Pushing org code to
a fork under your own account will be refused locally, before it reaches GitHub — so
work on branches in this repo.

Check what you have:

```bash
gh repo view razorpay-ai-tools/razorwire-beta --json viewerPermission
git push --dry-run origin HEAD    # authoritative; the API can lag
```

---

## Branch → PR → squash merge

**Never commit to `main`.** Branch, PR, squash.

```bash
git switch -c feat/short-description
# ... work ...
cd backend && uv run pytest -q    # must pass
npm run build                      # must pass
git push -u origin HEAD
gh pr create --base main
```

`npm run dev:all` starts both servers and creates any missing local env files. Copy
`backend/.env.example` → `backend/.env` and `.env.example` → `.env.local` first.

### Squash and merge, always

**Use "Squash and merge" on every PR.** One PR becomes one commit on `main`.

Why, for a four-person hackathon repo:

- `main` stays a readable list of changes, not 40 "wip" and "fix lint" commits.
- Reverting a feature is one `git revert`, which matters on demo day.
- Nobody has to rebase a shared branch to keep history linear.

Write the squash commit message properly — it is the one that survives. GitHub
pre-fills it with every commit subject concatenated; **replace that**. Follow the
message conventions below.

> **Repo settings.** Squash merge is already enabled. Making it the *only* option needs
> repo **admin**, which most of us do not have. Whoever does should run:
>
> ```bash
> gh api -X PATCH repos/razorpay-ai-tools/razorwire-beta \
>   -F allow_squash_merge=true \
>   -F allow_merge_commit=false \
>   -F allow_rebase_merge=false \
>   -F delete_branch_on_merge=true
> ```
>
> Until then it is a convention, so please honour it — the button order in the GitHub UI
> makes "Create a merge commit" the easy mistake.

### Branch names

```
feat/…    a new capability
fix/…     a bug
docs/…    documentation only
chore/…   tooling, cleanup, dependencies
```

---

## Commit messages

```
<type>(<scope>): <what changed, in the imperative>

Why it changed. What you decided against and why. Anything that will look
wrong to the next reader but is deliberate.

Co-Authored-By: ...   (if pairing, or if an agent wrote part of it)
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`.
Scopes in use: `contract`, `handoff`, `backend`, `api`, `web`, `feed`, `design`.

**The body is the valuable part.** Anyone can read the diff; nobody can read your
reasoning six weeks later. Record the decision, not the mechanics — especially when you
rejected an obvious alternative, because the next person will otherwise "fix" it back.

Real examples from this repo's history:

```
feat(backend): actually fetch aidocs, the differentiator was decoration
feat: storyboard contract with Veo as background-only layer
fix(feed): the source-doc links were unclickable and absent
```

---

## Before you open a PR

```bash
cd backend && uv run pytest -q             # 113 tests
npm run lint && npx tsc --noEmit           # or ./node_modules/.bin/eslint .
npm run build
node src/components/scenes/__check.mts     # scene dispatcher exhaustiveness
```

`npx` will silently download its own binaries if `node_modules` is empty, which makes
a clean-looking run meaningless. Run `npm install` first, or call
`./node_modules/.bin/…` directly.

Regenerate derived artifacts if you touched a contract:

```bash
npm run gen:types    # → contracts/*.schema.json, src/lib/storyboard.types.ts
```

`src/lib/storyboard.types.ts` is **generated**. Editing it by hand is a merge conflict
waiting to happen.

---

## Things that will get a PR sent back

**Secrets.** A gitleaks pre-commit hook runs, but it is a backstop, not permission to
be careless. The repo is public.

**Customer data or PII in a fixture.** Use the sample doc at
`public/samples/payment-routing-readiness-aidoc.md`, or invent something.

**Mixing the two storyboard shapes.** `Post.storyboard` holds the *internal* shape
(`scene.type`); `storyboard.json` on disk holds the *render* shape
(`scene.visual.kind`). Putting one where the other belongs makes the feed render six
blank frames with nothing raising an error. See `README.md` → *Two contracts*.

**Editing the generated types instead of the pydantic models.** The backend owns the
contract because it owns the pipeline.

**Hand-written duplicates of a generated artifact.** Two definitions that agree today
will not agree next week.

**A validator without a test that it fires.** A rule nobody proved is a rule nobody has.

---

## Where things live

`README.md` — what it is, how to run it, the current architecture, known gaps.
`docs/PLAN.md` — feasibility, stack decisions, the three-day plan, risk register.
`docs/DESIGN.md` — the design record and the fifteen things a review corrected.
`CONTRIBUTING.md` — this file.

If you make a decision worth remembering, it goes in a commit body and, if it changes
the shape of the thing, in `README.md`. Not in a Slack thread.
