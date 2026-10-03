# brand-engine

**An AI content assistant and auto-poster for creators in any niche.**

You describe your niche once. brand-engine then writes posts in your voice, grounded only in facts you
gave it, lets you review everything, and publishes on a schedule to LinkedIn, Instagram, Threads,
Bluesky, Dev.to, Hashnode and Blogger, even while your computer is off.

Fitness coach, food creator, designer, teacher, finance educator, developer, therapist, travel writer: the
engine knows nothing about any of them until you tell it. This repository contains no personal data.

```
 your niche + facts + past posts ──► knowledge base ──► Claude writes drafts ──► YOU review & approve
                                                                                        │
          LinkedIn · Instagram · Threads · Bluesky · Dev.to · Hashnode · Blogger ◄── scheduler posts on time
```

**Safety rails built in:** nothing is posted without your approval; the writer may only state facts you
provided (anything missing becomes a `[FILL: ...]` placeholder you must fill); numbers that aren't in your
facts are flagged; your tokens stay in `.env` and GitHub Secrets.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Get your own private copy](#2-get-your-own-private-copy)
3. [Install](#3-install)
4. [Tell it who you are](#4-tell-it-who-you-are)
5. [Give it your niche context (most important)](#5-give-it-your-niche-context-most-important)
6. [Connect the AI writer and your platforms](#6-connect-the-ai-writer-and-your-platforms)
7. [Create content](#7-create-content)
8. [Automate posting](#8-automate-posting)
9. [Your weekly routine](#9-your-weekly-routine)
10. [Troubleshooting](#10-troubleshooting)
11. [Command reference](#11-command-reference)

---

## 1. What you need

| Thing | Why | Cost |
|---|---|---|
| A computer (macOS, Windows or Linux) | to set up, write and review | - |
| [Python 3.10+](https://www.python.org/downloads/) (3.12 recommended) | runs the engine | free |
| [Git](https://git-scm.com/downloads) and a [GitHub](https://github.com) account | your private copy + 24/7 cloud posting | free |
| [Google Chrome](https://www.google.com/chrome/) (or Chromium / Edge) | turns carousel designs into PDFs and images | free |
| An [Anthropic API key](https://console.anthropic.com/) | the AI writer (Claude) | pay per use: usually cents per batch or article |
| Accounts on the platforms you want to post to | publishing | free |

Optional: the [GitHub CLI](https://cli.github.com/) (`gh`) makes a few steps one-liners.

## 2. Get your own private copy

Your copy will hold your drafts, schedule and photos, so it must be **private**.

**Easiest:** on this repository's GitHub page click **Use this template -> Create a new repository**, choose
**Private**, create it, then download it to your computer:

```bash
git clone https://github.com/YOUR-USERNAME/YOUR-REPO-NAME.git
```

**Without the template button** (with the GitHub CLI installed and logged in):

```bash
git clone https://github.com/RAMAN-SHUKLA/brand-engine-template.git my-brand-engine
```
```bash
cd my-brand-engine && git remote remove origin && gh repo create my-brand-engine --private --source=. --push
```

Do not fork: forks of a public repository are public.

## 3. Install

Open a terminal (macOS: Terminal app; Windows: PowerShell) **inside your copy's folder**, then:

**macOS / Linux**
```bash
python3 -m venv .venv
```
```bash
source .venv/bin/activate
```
```bash
pip install -r requirements.txt
```
```bash
cp .env.example .env
```

**Windows (PowerShell)**
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Every time you open a new terminal to use brand-engine, activate it again (`source .venv/bin/activate` or
`.venv\Scripts\Activate.ps1`). Once it is active, `python` works the same on every system.
If Windows refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

Check it works:

```bash
python cli.py --help
```

## 4. Tell it who you are

Open `config.yaml` in any text editor and fill in:

- **`timezone`**: where you live, e.g. `America/New_York`, `Europe/London`, `Asia/Kolkata`. Every posting time is read in it.
- **`person`**: your name (exactly as on your profiles), handle, a one-line headline, location, and the links you use.
- **Your photo:** save a square headshot as `assets/me/avatar.jpg`. It appears on carousels and share cards. Put any
  other photos of yourself in `assets/me/` too.

## 5. Give it your niche context (most important)

The writer is only as good as the context you give it. It reads four things, in this order of importance:

| What | Where | What it does |
|---|---|---|
| Your niche | `config.yaml` -> `niche` | topic, angle, audience, pillars, voice, keywords, hashtags, call to action, rules |
| Your facts | `data/manual_facts.yaml` | the ONLY things it may claim about you: credentials, results, milestones, stories |
| Your voice | `data/voice_samples.md` | 3-10 of your best past posts; it copies your rhythm and tone |
| Extra sources (optional) | `python cli.py ingest --...` | bio PDF, LinkedIn data export, web pages, GitHub |

**After changing any of them, run `python cli.py ingest`.**

### 5a. The `niche` block

| Field | Write | Weak | Strong |
|---|---|---|---|
| `topic` | what you post about, in one line | "fitness" | "simple strength training for busy parents over 30" |
| `description` | 3-6 sentences: your angle, experience, what you believe that others in your niche don't | "I love fitness" | "Ten years coaching parents. I think most programs fail because they assume 60 free minutes. Everything I teach fits in 20 minutes with one kettlebell." |
| `audience` | who you talk to; the first one is the default reader | "everyone" | "parents aged 30-45 who have tried and quit the gym" |
| `goal` | what the content should achieve for you | "grow" | "grow a newsletter of people who train at home" |
| `pillars` | 3-5 recurring themes, each with a short `key`, a `name` and an `angle` | one pillar | teach / story / myths / opinion, each with a specific angle |
| `voice` | how you sound | "professional" | "Warm, blunt, funny. Short sentences. Talks like a friend who happens to be a coach." |
| `keywords` | phrases your audience types into search | - | `["home workout", "kettlebell for beginners"]` |
| `hashtags` | a pool to rotate (3-5 are picked per post) | - | `["#HomeWorkout", "#StrengthTraining", "#FitOver30"]` |
| `call_to_action` | what readers should do next; empty = end with a question | - | "Follow for a new 20-minute workout every Monday" |
| `content_rules` | rules in plain language | - | `["Never give medical advice", "Use metric units"]` |
| `avoid_mentions`, `banned_phrases` | names and phrases that must never appear | - | competitor names, overused buzzwords |

Three short examples to copy from:

```yaml
# Food creator
niche:
  topic: "15-minute vegetarian dinners for people who hate cooking"
  description: >
    Former restaurant line cook who now cooks for a family of four on weeknights. I care about speed,
    cheap ingredients and food that actually tastes good, not pretty plating.
  audience: ["busy adults who order takeout 4+ nights a week"]
  pillars:
    - {key: recipes, name: "Quick recipes", angle: "One dish, 15 minutes, under 8 ingredients"}
    - {key: skills, name: "Kitchen skills", angle: "One technique that makes every meal faster"}
    - {key: story, name: "Kitchen stories", angle: "Disasters, wins and lessons from 15 years of cooking"}
  voice: "Casual, funny, no food snobbery. Short lines."
  call_to_action: "Save this for your next weeknight"
```

```yaml
# Personal finance educator
niche:
  topic: "money basics for people in their first job"
  description: >
    Certified financial planner. I explain budgeting, saving and investing without jargon and
    without selling products. I believe boring index funds beat clever picks for most people.
  audience: ["22-30 year olds with their first salary and no money education"]
  content_rules: ["Never recommend a specific stock", "Always say this is education, not financial advice"]
```

```yaml
# Freelance designer
niche:
  topic: "branding and visual identity for small businesses"
  audience: ["small business owners who are about to rebrand", "junior designers"]
  pillars:
    - {key: teardown, name: "Brand teardowns", angle: "What a real brand gets right and wrong, and why"}
    - {key: process, name: "My process", angle: "How a project goes from brief to final files"}
    - {key: business, name: "Freelance business", angle: "Pricing, clients, contracts, lessons"}
```

### 5b. Your facts: `data/manual_facts.yaml`

Each fact becomes a numbered item (F001, F002, ...) that posts can cite. Write them as complete, true
sentences with the numbers that matter. If a fact isn't here (or in an ingested source), the writer will not
claim it; it writes `[FILL: ...]` instead and asks you.

```yaml
facts:
  - text: "Certified personal trainer (NASM) since 2019, coaching 200+ clients online."
    kind: role
  - text: "My newsletter 'Strong at 40' has 4,000 subscribers and goes out every Monday."
    kind: stat
    url: https://example.com/newsletter
```

Good things to add: credentials and roles, client or audience numbers, results (yours and, with permission,
clients'), products and programs, talks and features, awards, memorable stories from your journey.

### 5c. Your voice: `data/voice_samples.md`

Paste 3-10 of your best past posts below the instructions comment, separated by `---`. Real posts teach the
writer far more than any description. Only paste your own, accurate posts: facts in them count as true.

### 5d. Optional extra sources

```bash
python cli.py ingest --resume "path/to/bio-or-media-kit.pdf"      # any PDF about you
python cli.py ingest --sites https://example.com/about            # pages about you or your work
python cli.py ingest --linkedin "path/to/LinkedIn-export.zip"     # your LinkedIn posts, roles, honors
```

LinkedIn export: LinkedIn -> **Me -> Settings & Privacy -> Data privacy -> Get a copy of your data**. It
includes your past posts (great voice material) and ignores other people's data. Developers can also set
`ingest.github_user` to turn public repositories into facts.

### 5e. Build the knowledge base

```bash
python cli.py ingest
```

Then open **`data/brand_brief.md`**: it is exactly what the writer knows about you. If something is wrong or
missing, fix the source and run `ingest` again.

## 6. Connect the AI writer and your platforms

All keys go in the `.env` file in your folder (it is never committed). You only need the platforms you use;
empty keys are skipped. Keys that expire (LinkedIn, Instagram, Threads: about every 60 days) must be renewed
in `.env` **and** in your GitHub secrets.

| Platform | What it posts | Keys in `.env` | Check it |
|---|---|---|---|
| Claude (required) | writes everything | `ANTHROPIC_API_KEY` | `python cli.py calendar --ai 2` |
| LinkedIn | text, image, article and carousel (PDF) posts | `LINKEDIN_ACCESS_TOKEN` | `python cli.py linkedin-check` |
| Instagram | carousels | `INSTAGRAM_ACCOUNT_ID`, `INSTAGRAM_ACCESS_TOKEN` + Cloudinary keys | `python cli.py ig-check` |
| Threads | text and image posts | `THREADS_ACCESS_TOKEN` | see below |
| Bluesky | text and image posts | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | see below |
| Dev.to | long-form articles | `DEVTO_API_KEY` | `python cli.py publish --slug <slug>` (dry run) |
| Hashnode | long-form articles | `HASHNODE_TOKEN` (+ optional `HASHNODE_PUBLICATION_ID`) | same |
| Blogger | long-form articles | `BLOGGER_CLIENT_ID`, `BLOGGER_CLIENT_SECRET`, `BLOGGER_REFRESH_TOKEN` | `python cli.py blogger-check` |
| Medium | long-form articles (manual import) | none | - |
| X / Twitter | thread text is generated in `drafts/<slug>/x_thread.txt`; post it yourself | none | - |

### Claude (the writer)

1. Sign in at [console.anthropic.com](https://console.anthropic.com/), add credits under **Billing**.
2. **API Keys -> Create key**, copy it, and paste it into `.env` as `ANTHROPIC_API_KEY=...`.

The model and how hard it thinks are set under `writer` in `config.yaml` (`effort: low` is cheaper and faster,
`high` writes better).

### LinkedIn (~15 minutes)

Posts go to your **personal profile**, never to a Page. LinkedIn only needs a Page as the owner of the app.

1. Go to https://www.linkedin.com/developers/apps -> **Create app**. Attach it to a LinkedIn Page (create a free
   one if you have none), add a name, a logo and a privacy-policy URL (any page on your website works).
2. **Settings** tab -> **Verify** the app with the Page.
3. **Products** tab -> request **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect** (instant).
4. **Auth** tab -> add the redirect URL `https://www.linkedin.com/developers/tools/oauth/redirect`.
5. **Auth** tab -> **OAuth 2.0 tools** -> **Create token** -> tick `openid`, `profile`, `w_member_social` ->
   sign in -> copy the token into `.env` as `LINKEDIN_ACCESS_TOKEN=...`.
6. Run `python cli.py linkedin-check`.

The token lasts about 60 days; when posting reports a 401, repeat step 5. If LinkedIn returns a 426 "version"
error, set `publish.linkedin.api_version` in `config.yaml` to a recent month (`YYYYMM`).

### Instagram (~20 minutes) + Cloudinary (~3 minutes)

Instagram's API only accepts images from public URLs, so slides are uploaded to a free Cloudinary account first.

1. In the Instagram app, switch to a **Professional account** (Creator or Business) and connect it to a
   **Facebook Page** (Settings -> Account type and tools / Accounts Center).
2. Create an app at [developers.facebook.com/apps](https://developers.facebook.com/apps) (type **Business**) and add
   the Instagram Graph API / "manage content on Instagram" use case.
3. Open the [Graph API Explorer](https://developers.facebook.com/tools/explorer), select your app, choose
   **User Token**, add the permissions `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`, then **Generate Access Token**.
4. Turn it into a 60-day token (App ID and App Secret are under the app's **Settings -> Basic**):
   ```bash
   curl "https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN"
   ```
5. Find your Instagram account ID (the `instagram_business_account` id in the answer):
   ```bash
   curl "https://graph.facebook.com/v21.0/me/accounts?fields=name,instagram_business_account&access_token=LONG_TOKEN"
   ```
6. Put both in `.env` as `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_ACCOUNT_ID`.
7. Sign up free at [cloudinary.com](https://cloudinary.com) -> Dashboard -> copy **Cloud name**, **API Key**,
   **API Secret** into `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`.
8. Run `python cli.py ig-check`.

### Threads (~20 minutes)

1. Make sure your Instagram/Threads account is **Professional**.
2. [developers.facebook.com/apps](https://developers.facebook.com/apps) -> **Create App** -> add the use case
   **Access the Threads API**.
3. App Dashboard -> **Settings -> Basic**: note the **Threads App ID** and **Threads App secret** (not the top-level ones).
   Under Client OAuth Settings, add a redirect URI you own (any `https://` page of yours).
4. **App roles -> Roles -> Add People -> Threads Tester** -> your Threads username. Then in Threads:
   **Settings -> Account -> Website permissions** -> accept the invite.
5. Open in a browser (fill in the two values), log in, approve, and copy the `code` from the address you land on
   (drop the trailing `#_`):
   ```
   https://threads.com/oauth/authorize?client_id=<THREADS_APP_ID>&redirect_uri=<REDIRECT_URI>&scope=threads_basic,threads_content_publish&response_type=code
   ```
6. Exchange the code (valid 1 hour) for a short-lived token, then for a 60-day token:
   ```bash
   curl -X POST https://graph.threads.com/oauth/access_token -F client_id=<THREADS_APP_ID> -F client_secret=<THREADS_APP_SECRET> -F grant_type=authorization_code -F redirect_uri=<REDIRECT_URI> -F code=<CODE>
   ```
   ```bash
   curl "https://graph.threads.com/access_token?grant_type=th_exchange_token&client_secret=<THREADS_APP_SECRET>&access_token=<SHORT_LIVED_TOKEN>"
   ```
7. Put the long-lived token in `.env` as `THREADS_ACCESS_TOKEN`. Check it:
   `python -c "from brand_engine.publish import threads; print(threads.login())"`.
8. Refresh before 60 days: `curl "https://graph.threads.com/refresh_access_token?grant_type=th_refresh_token&access_token=<CURRENT_TOKEN>"`.

### Bluesky (~2 minutes)

Bluesky -> **Settings -> Privacy and security -> App passwords -> Add**. Put your handle (e.g.
`yourname.bsky.social`) in `BLUESKY_HANDLE` and the app password (never your real password) in
`BLUESKY_APP_PASSWORD`. Check: `python -c "from brand_engine.publish import bluesky; print(bluesky.login()['handle'])"`.
Optional: `python cli.py bluesky-links` posts and pins a thread with your links (`publish.bluesky.links_post`).

### Dev.to, Hashnode, Medium (long-form)

- **Dev.to:** Settings -> Extensions -> **DEV Community API Keys** -> `DEVTO_API_KEY`.
- **Hashnode:** [hashnode.com/settings/developer](https://hashnode.com/settings/developer) -> Personal Access Token -> `HASHNODE_TOKEN`.
- **Medium** has no publishing API: `publish` exports an HTML file and prints how to use **Import a story**.

### Blogger (~10 minutes)

1. [console.cloud.google.com](https://console.cloud.google.com) -> new project -> **APIs & Services -> Library** ->
   enable **Blogger API v3**.
2. **OAuth consent screen** -> External -> add the scope `https://www.googleapis.com/auth/blogger` and yourself as a
   test user -> **Publish app** (in "Testing" mode Google expires the token after 7 days).
3. **Credentials -> Create credentials -> OAuth client ID -> Desktop app** -> copy the ID and secret into
   `BLOGGER_CLIENT_ID` and `BLOGGER_CLIENT_SECRET`; put your blog's ID in `config.yaml` -> `publish.blogger.blog_id`.
4. Run `python cli.py blogger-auth` (a browser opens; approve). It saves `BLOGGER_REFRESH_TOKEN` into `.env`.
5. Check: `python cli.py blogger-check`.

## 7. Create content

### 7a. A week of short posts (LinkedIn, Threads, Bluesky)

```bash
python cli.py batch new --count 7 --notes "Launching my spring challenge Monday; mention the free guide"
```

Claude writes 7 posts spread across your pillars into `data/batches/<week>/`. Then:

1. **Read `data/batches/<week>/review.md`.** Every post shows the facts it used, numbers to double-check,
   warnings and an image idea.
2. **Edit** any post's `text` directly in `data/batches/<week>/posts.json` if you like, then refresh the review:
   `python cli.py batch render --week <week>`.
3. **Approve** (drop the ones you don't want): `python cli.py batch approve --week <week> --drop P03`
4. **Schedule** into your next free slots: `python cli.py batch schedule --week <week>`
5. **Send to the cloud runner:** `python cli.py sync`

Other platforms have different length limits, so write a separate batch for each:

```bash
python cli.py batch new --platform threads --week 2026-W41-threads --count 7
```
```bash
python cli.py batch schedule --week 2026-W41-threads --platform threads
```

To attach an image to a short post, add `"images": ["assets/me/photo.jpg"]` (or an `https://` URL; Threads
needs a URL) to that post in `posts.json`.

### 7b. Long-form articles (+ a LinkedIn post and an X thread for each)

```bash
python cli.py calendar            # topic ideas from your pillars and facts
python cli.py calendar --ai 8     # 8 more ideas from Claude
python cli.py write --topic T003  # or: --title "My title" --notes "points to cover"
```

The draft lands in `drafts/<slug>/` (`post.md`, `linkedin.txt`, `x_thread.txt`, `meta.json`). Fix every
`[FILL: ...]`, check `claims_to_verify` and `warnings` in `meta.json`, then:

```bash
python cli.py approve --slug <slug>
python cli.py publish --slug <slug>                    # dry run: shows what would go where
python cli.py publish --slug <slug> --confirm --live   # publish now
python cli.py queue add --slug <slug> --at "2026-10-20 10:00" --platforms devto,linkedin   # or schedule it
```

The first platform in `publish.primary_platform` gets the original; the others link back to it. To post the
LinkedIn version with an image, add `cover_image: assets/me/photo.jpg` to the front matter of `post.md`.

### 7c. Carousels (Instagram and LinkedIn)

A carousel is a small JSON file, `data/carousels/<slug>.json`. Start by rendering the example:

```bash
python -m brand_engine.carousel.render data/carousels/example-deck.json
```

That writes `assets/carousels/example-deck.pdf` (with your name and photo on every slide) and a preview sheet in
`assets/carousel/decks/example-deck/`. Copy the example, change the text, pick a `theme` (`violet`, `sky`,
`cream`, `mint`, `ink`, `rose`, `tensor_dark`, `tensor_clean`, `tensor_editorial`), and add your photos from
`assets/me/`. All slide types are documented at the top of `brand_engine/carousel/render.py`.

Tip: an AI assistant can write decks for you. Open this folder in Claude Code (or a similar tool) and ask:
*"Make a 6-slide carousel deck about <topic> following AGENTS.md, then render it."*

- **Instagram now:** `python cli.py ig-publish <slug>` (dry run), then add `--confirm`.
- **Instagram on a schedule:** add an item to `data/post_queue.json`:
  ```json
  {"id": "IG001", "carousel": "<slug>", "slug": "<slug>", "platforms": ["instagram"],
   "scheduled_at": "2026-10-20 12:00", "status": "queued", "created": "2026-10-15 10:00", "results": []}
  ```
- **LinkedIn:** give a short post in a batch a `"document": "assets/carousels/<slug>.pdf"` field; it is posted as
  a swipeable document.

Commit the PDFs (`python cli.py sync` does it) so the cloud runner can post them.

## 8. Automate posting

Scheduled posts live in `data/post_queue.json`. Something has to run `python cli.py queue run` regularly; it
posts whatever is due, skips anything more than `publish.queue.max_late_hours` late, and never double-posts.

### Option A: GitHub Actions (recommended, works with your computer off)

1. Save your setup to your private GitHub copy once (`.env` is never included):
   ```bash
   git add -A && git commit -m "My setup" && git push
   ```
2. **Add your keys as secrets:** your repo -> **Settings -> Secrets and variables -> Actions -> New repository
   secret**, one per key in your `.env` that you use (same names). With the GitHub CLI, for example:
   ```bash
   gh secret set LINKEDIN_ACCESS_TOKEN --body "$(grep ^LINKEDIN_ACCESS_TOKEN= .env | cut -d= -f2-)"
   ```
3. **Allow the runner to save its progress:** **Settings -> Actions -> General -> Workflow permissions -> Read
   and write permissions**.
4. **Turn it on** (it does nothing until you do): **Settings -> Secrets and variables -> Actions -> Variables ->
   New variable** `BRAND_ENGINE_ENABLED` = `true`, or:
   ```bash
   gh variable set BRAND_ENGINE_ENABLED --body true
   ```
5. **Test:** **Actions** tab -> **post-queue** -> **Run workflow**. It should finish green.

From now on, after you schedule anything, run `python cli.py sync` so the cloud sees it.

**Posting on the minute (optional, recommended).** GitHub's built-in timer can run hours late at busy times.
A free external clock fixes it:

1. GitHub -> your avatar -> **Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens ->
   Generate new token**: only your brand-engine repo, permission **Actions: Read and write**, nothing else.
2. [cron-job.org](https://cron-job.org) (free) -> **Create cronjob**:
   - URL: `https://api.github.com/repos/<YOUR_USERNAME>/<YOUR_REPO>/actions/workflows/post-queue.yml/dispatches`
   - Schedule: every hour at minute 2, in your timezone
   - Advanced: method **POST**, body `{"ref":"main"}`, headers `Authorization: Bearer <token>`,
     `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `User-Agent: brand-engine-cron`
3. **Run now**: expect **HTTP 204**, and a new run in your Actions tab. (401 = token wrong or expired;
   404 = token lacks access to this repo.)

### Option B: your own computer (must be on at posting time)

- **macOS / Linux:** run `crontab -e` and add (with your real path):
  `*/15 * * * * /path/to/your-copy/scheduler/run_queue.sh`
- **Windows:** run once in PowerShell: `powershell -ExecutionPolicy Bypass -File scheduler\register_windows_task.ps1`

Logs go to `data/queue_runner.log`.

## 9. Your weekly routine

About 15-30 minutes, once a week:

1. `python cli.py batch new --notes "<what's happening this week>"` (plus one per extra platform)
2. Read `review.md`, edit, `batch approve`, `batch schedule`
3. Optional: one article (`write`) or one carousel
4. `python cli.py sync`
5. Every ~50 days: renew the LinkedIn / Instagram / Threads tokens (in `.env` and GitHub secrets)

Whenever something new happens (a result, a launch, a talk), add it to `data/manual_facts.yaml` and run
`python cli.py ingest` so future posts can mention it.

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| "No knowledge base yet" | Run `python cli.py ingest`. |
| Posts sound generic | Make `niche.description` and `voice` more specific, add real posts to `data/voice_samples.md`, add facts; then `ingest`. |
| Lots of `[FILL: ...]` | The writer needs facts it doesn't have. Add them to `data/manual_facts.yaml`, then `ingest`. |
| 401 when posting | That platform's token expired. Make a new one, update `.env` and the GitHub secret. |
| LinkedIn 426 error | Set `publish.linkedin.api_version` to a recent `YYYYMM`. |
| "No Chrome/Edge found" | Install Chrome, or set `CHROME_PATH=` in `.env` to its full path. |
| Posts go out at the wrong time | Check `timezone` in `config.yaml`. |
| Cloud runner never posts | Check: `BRAND_ENGINE_ENABLED` is `true`, secrets exist, workflow permissions are read/write, and you ran `python cli.py sync`. |
| Cloud runner posts hours late | Set up the cron-job.org clock (section 8). |
| A post was skipped | It was more than `publish.queue.max_late_hours` late. |

## 11. Command reference

| Command | What it does |
|---|---|
| `python cli.py ingest [--resume PDF] [--sites URL ...] [--linkedin ZIP]` | rebuild the knowledge base from your config, facts, voice samples and sources |
| `python cli.py batch new [--count N] [--platform P] [--notes "..."] [--week NAME] [--append]` | write a batch of short posts |
| `python cli.py batch list` / `show --week W` / `render --week W` | list batches / print a review / refresh a review after editing |
| `python cli.py batch approve --week W [--drop P03] [--only P01,P02]` | approve posts |
| `python cli.py batch schedule --week W [--platform P]` | put approved posts into free time slots |
| `python cli.py calendar [--ai N] [--replace]` | topic ideas for articles |
| `python cli.py write --topic T001` or `--title "..."` | write an article + LinkedIn post + X thread |
| `python cli.py approve --slug S` | approve an article |
| `python cli.py publish --slug S [--confirm] [--live]` | publish an article now (dry run by default) |
| `python cli.py queue add --slug S --at "YYYY-MM-DD HH:MM" [--platforms ...]` | schedule an article |
| `python cli.py queue list` / `run [--dry-run]` / `remove --id Q001` | see, run or edit the schedule |
| `python cli.py ig-publish SLUG [--confirm]` | post a carousel to Instagram |
| `python cli.py media-kit` | one-page media kit for brands (`outreach_out/media_kit.md` + `.html`) |
| `python cli.py sync` | save your queue, batches and carousels to GitHub |
| `python cli.py status` | what is in the knowledge base, calendar and drafts |
| `python cli.py linkedin-check` / `ig-check` / `blogger-check` | test platform keys |

### Project layout

```
config.yaml              who you are, your niche, timezone, posting times, AI settings
.env                     your keys (never committed; copy from .env.example)
AGENTS.md                content rules for AI assistants working in this folder
data/manual_facts.yaml   facts the writer may use
data/voice_samples.md    your past posts (voice reference)
data/batches/            weekly short-post batches
data/carousels/          carousel decks (JSON)
data/post_queue.json     the posting schedule
assets/me/               your photos (avatar.jpg)
assets/carousels/        rendered carousel PDFs
drafts/<slug>/           long-form drafts
outreach_out/            media kit
brand_engine/            the engine (ingest, generate, carousel, publish)
scheduler/               run the queue from your own computer
.github/workflows/       the cloud runner
```

### Privacy checklist

- Keep your copy **private**. Never commit `.env`; never paste tokens anywhere except `.env` and GitHub secrets.
- If a token ever leaks, revoke it on the platform first, then replace it.
- Generated personal data (`data/knowledge_base.json`, `data/brand_brief.md`, ingested exports) is gitignored.
