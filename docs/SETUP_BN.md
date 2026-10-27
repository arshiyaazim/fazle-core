# Fazle Core — সম্পূর্ণ সেটআপ গাইড (বাংলা)

> **কোনটা বাধ্যতামূলক, কোনটা ঐচ্ছিক** — এই ডকুমেন্টটা ঠিক সেই প্রশ্নের উত্তর
> দেয়: “WhatsApp MCP সার্ভার, Ollama লোকাল মডেল, Hermes এজেন্ট — সব কি ইনস্টল
> করতে হবে?”
>
> ইংরেজি রেফারেন্স: `README.md` §4 (Installation) ও §5 (External dependencies)।
> অটো-চেক: `bash scripts/check_stack.sh`

---

## ০. এক নজরে উত্তর (TL;DR)

**না। WhatsApp MCP সার্ভার (`fazle-mcp`) বা Hermes এজেন্ট — কোনোটাই `fazle-core`
চালানোর জন্য লাগে না।** এগুলো আলাদা রিপো/সার্ভিস, আর এগুলো `fazle-core`-কে
ব্যবহার করে (উল্টোটা নয়)।

`fazle-core` নিজে চালাতে আসলে যা লাগে তা হলো **তিনটে জিনিস**:

1. Python 3.10/3.11 + `requirements.txt`-এর প্যাকেজ
2. **PostgreSQL 15+** (এটা ছাড়া অ্যাপ স্টার্টই হয় না)
3. একটা `.env` ফাইল যাতে অন্তত `DATABASE_URL` আর `INTERNAL_API_KEY` আছে

বাকি সবই *ফিচার-ভিত্তিক ঐচ্ছিক*: কোনোটা না থাকলে শুধু সেই একটা ফিচার বন্ধ থাকে,
অ্যাপ পড়ে যায় না।

| কম্পোনেন্ট | বাধ্যতামূলক? | কী কাজ করে | না থাকলে |
|---|---|---|---|
| Python + `requirements.txt` | ✅ হ্যাঁ | অ্যাপ রানটাইম | অ্যাপ চলবে না |
| PostgreSQL 15+ | ✅ হ্যাঁ | সব ডেটা (RBAC, ড্রাফট, পে-রোল, KB) | `lifespan()`-এ `init_db()` ফেল → **অ্যাপ স্টার্ট হয় না** |
| `INTERNAL_API_KEY` | ✅ হ্যাঁ (কার্যত) | সব admin/mutation API-র `X-Internal-Key` | ড্যাশবোর্ড/API সব ৪০৩ |
| Redis | ⚪ না | শেয়ার্ড cooldown/state, কিউ হেল্পার | in-memory fallback |
| **Ollama + `hermes3:3b`** | ⚪ না | লোকাল AI রিপ্লাই (চেইনের ৩য় ধাপ) | টেক্সট fallback রিপ্লাই, বা OmniRoute/Groq |
| **WhatsApp bridge 1/2/3** | ⚪ না* | আসল WhatsApp ইনবাউন্ড/আউটবাউন্ড | কোনো WhatsApp মেসেজ আসবে/যাবে না (*শুধু তখনই লাগে যখন সত্যিকারের WhatsApp চালাবেন) |
| **WhatsApp MCP (`fazle-mcp`)** | ⚪ না | Hermes/এজেন্টকে Core-এর টুল দেওয়ার MCP সার্ভার | এজেন্ট টুল লেয়ার থাকবে না; Core অক্ষত |
| **Hermes runner** | ⚪ না | Admin `HERMES ...` রিলে, কাস্টমার ডিসপ্যাচ | fail-closed, লোকাল চেইনে নেমে যায় |
| OmniRoute / 9Router | ⚪ না | প্রাইমারি AI গেটওয়ে | Ollama → fallback টেক্সট |
| Meta Cloud API | ⚪ না | Meta-র দিকের WhatsApp | শুধু bridge পথে চলবে |
| Qdrant | ⚪ না | হাইব্রিড ভেক্টর RAG | embedded/BM25 সার্চ |
| Media processor | ⚪ না | OCR/ভয়েস ট্রান্সক্রিপ্ট/ডকুমেন্ট | মিডিয়া `media_unprocessed` থাকে |
| LocationWhere | ⚪ না | এমপ্লয়ি লোকেশন | লোকেশন ফিচার বন্ধ |

---

## ১. কেন WhatsApp MCP সার্ভার লাগে না (গুরুত্বপূর্ণ)

অনেকে ভাবেন “WhatsApp চালাতে MCP লাগবে”। এই আর্কিটেকচারে তা নয়। ডেটা-ফ্লো এমন:

```
WhatsApp Web  ──►  Bridge 1/2/3 (আলাদা সার্ভিস, whatsmeow-ভিত্তিক)
                      │
                      ├─ HTTP :8081/:8082/:8083  ◄── Core পাঠানোর জন্য কল করে
                      └─ SQLite store/messages.db ◄── Core প্রতি ৫ সেকেন্ডে পোল করে
                                  │
                                  ▼
                          fazle-core :8200   (এই রিপো)
                                  │  X-Internal-Key দিয়ে HTTP API
                                  ▼
                          fazle-mcp  (MCP টুল সার্ভার, আলাদা রিপো)
                                  │  MCP protocol
                                  ▼
                          Hermes / Earth এজেন্ট (hermes-runner / hermes-agent)
```

- **Core নিজেই bridge-এর SQLite সরাসরি পড়ে** (`modules/fazle_bridge_poller`) —
  মাঝখানে MCP নেই।
- **`fazle-mcp` হলো Core-এর *গ্রাহক*** — `fazle_core_client.py` দিয়ে
  `http://127.0.0.1:8200`-এ `X-Internal-Key` হেডার পাঠায়। এটা Hermes-কে
  `send_whatsapp`, `get_dlq_status`, `identity_lookup` ইত্যাদি টুল দেয়।
- অর্থাৎ `fazle-mcp` ইনস্টল না করলে Core-এর WhatsApp ইনজেস্ট/ড্রাফট/পে-রোল
  কিছুই কমে না — শুধু **এজেন্টের হাত** থাকে না।

তাই সিদ্ধান্তটা সরল:

- শুধু **অ্যাপ + ড্যাশবোর্ড + WhatsApp অটো-ড্রাফট** চান → MCP/Hermes ছাড়াই হবে।
- চান **এজেন্ট (Hermes/Earth) নিজে টুল চালিয়ে কাজ করুক** → তখন `fazle-mcp`
  আর `hermes-runner` লাগবে (দুটোই আলাদা রিপো, এই রিপোতে vendored নয়)।

---

## ২. ধাপে ধাপে সেটআপ — কোন লেভেল পর্যন্ত যাবেন

### L1 — শুধু অ্যাপ চালু (সবচেয়ে কম): ড্যাশবোর্ড + API + ডেটাবেস

**যা লাগবে:** Python, PostgreSQL, `.env`।

```bash
# 1) PostgreSQL (Docker থাকলে সবচেয়ে সহজ)
docker run -d --name fazle-pg \
  -e POSTGRES_USER=fazle -e POSTGRES_PASSWORD=fazle_local_password \
  -e POSTGRES_DB=fazle_core -p 127.0.0.1:5432:5432 postgres:15

# 2) কোড + venv
git clone https://github.com/arshiyaazim/fazle-core.git
cd fazle-core
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 3) .env  (এই রিপোতে .env.example যোগ করা হয়েছে)
cp .env.example .env
chmod 600 .env
#   DATABASE_URL=postgresql://fazle:fazle_local_password@127.0.0.1:5432/fazle_core
#   INTERNAL_API_KEY=<লম্বা র‍্যান্ডম স্ট্রিং>
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 4) স্কিমা তৈরি
.venv/bin/python db/migrate.py --dry-run   # কী কী চলবে দেখুন
.venv/bin/python db/migrate.py

# 5) রান
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8200

# 6) যাচাই
curl -fsS http://127.0.0.1:8200/health | python3 -m json.tool
```

খোলার ঠিকানা: `http://127.0.0.1:8200/` (ড্যাশবোর্ড SPA — JS আপনার API key
চাইবে), `http://127.0.0.1:8200/docs`।

এই অবস্থাতেই পাওয়া যায়: পে-রোল ইঞ্জিন, এসকর্ট রোস্টার, ড্রাফট রিভিউ,
RBAC, নলেজ-বেস, ব্যাকআপ, শিডিউলার, সব read/write API।
যা পাওয়া যায় না: কোনো আসল WhatsApp মেসেজ (bridge নেই), এজেন্ট টুল (MCP নেই)।

> ⚠️ **নিরাপত্তা:** `.env`-এ `AUTO_REPLY_ENABLED=false` আর `OUTBOUND_ENABLED=false`
> রাখুন। শুধু লোকালি চালালেও `INTERNAL_API_KEY` ফাঁকা রাখবেন না।

---

### L2 — + লোকাল AI (Ollama + Hermes মডেল)

Ollama না থাকলে রিপ্লাই-চেইন (`OmniRoute → Groq → Ollama/Hermes → fallback`)
শেষ ধাপে গিয়ে শুধু একটা ভদ্র fallback টেক্সট দেয়। লোকাল মডেল চাইলে:

```bash
# Ollama ইনস্টল (Linux)
curl -fsSL https://ollama.com/install.sh | sh
ollama serve            # অথবা systemd: systemctl enable --now ollama
ollama pull hermes3:3b  # ~২ GB, ডিফল্ট মডেল
ollama list             # hermes3:3b দেখা যাবে
```

`.env`-এ:

```env
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=hermes3:3b
OLLAMA_REPLY_DISABLED=false
OLLAMA_INFER_CONCURRENCY=1   # লোকাল মডেলে একসাথে ১টার বেশি হলে টাইমআউট হয়
```

যাচাই: `curl -fsS http://127.0.0.1:11434/api/tags`

> নোট: `hermes3` হলো Ollama-লাইব্রেরির মডেল-পরিবার; `hermes-agent` /
> `hermes-runner` রিপোর সাথে এর কোনো সম্পর্ক নেই — নামের মিলটা কাকতালীয়।
> Resolver ক্রম: `hermes3:3b` → `hermes3` → `hermes3:latest` → `hermes` →
> `hermes:latest`, না পেলে `OLLAMA_MODEL`।

GPU না থাকলে `hermes3:3b`-ই রাখুন; বড় মডেল ৪৫ সেকেন্ডের রিপ্লাই টাইমআউট ছাড়াবে।

---

### L3 — + আসল WhatsApp (bridge)

**এটাই সেই জায়গা যেখানে “WhatsApp ইন্টিগ্রেশন” আসলে লাগে** — কিন্তু সেটা
*bridge*, MCP নয়। bridge এই রিপোতে নেই (README স্পষ্ট বলছে: “Separate
repository/binaries. Not vendored here.”)। যা লাগবে:

1. প্রতিটি WhatsApp নাম্বারের জন্য একটি bridge প্রসেস (Bridge1=HR,
   Bridge2=OPS, Bridge3=REC2), সাধারণত `whatsapp-mcp`/`whatsmeow`-ভিত্তিক।
2. প্রতিটির নিজের `store/messages.db` + `store/whatsapp.db` (WhatsApp Web
   সেশন, QR স্ক্যান করে একবার লগইন)।
3. প্রতিটি bridge-এর HTTP এন্ডপয়েন্ট — ডিফল্ট পোর্ট:

| Bridge | ডিফল্ট URL | ডেটাবেস পাথ (ডিফল্ট) |
|---|---|---|
| bridge1 (HR) | `http://127.0.0.1:8082` | `/home/azim/whatsapp1/store/messages.db` |
| bridge2 (OPS) | `http://127.0.0.1:8081` | `/home/azim/whatsapp2/store/messages.db` |
| bridge3 (REC2) | `http://127.0.0.1:8083` | `/home/azim/whatsapp3/store/messages.db` |

`.env`-এ URL/পাথ/নাম্বার বসান (লোকাল মেশিনে পাথ অবশ্যই বদলান):

```env
BRIDGE1_URL=http://127.0.0.1:8082
BRIDGE1_NUMBER=8801XXXXXXXXX
BRIDGE1_DB_PATH=/srv/whatsapp1/store/messages.db
BRIDGE1_WHATSAPP_DB_PATH=/srv/whatsapp1/store/whatsapp.db
# ... একইভাবে BRIDGE2_*, BRIDGE3_*
BRIDGE_WEBHOOK_SECRET=
WEBHOOK_SIGNATURE_ENFORCEMENT=false   # bridge HMAC পাঠানো নিশ্চিত হওয়ার আগে true করবেন না
```

যাচাই: `curl -fsS http://127.0.0.1:8082/health` (প্রতিটি bridge) এবং
`bash scripts/check_stack.sh`।

**Important:** bridge-এর দিকে যাওয়া/আসা বন্ধ থাকলেও Core ক্র্যাশ করে না — শুধু
লগে warning দেয় আর পোলার অপেক্ষা করে; bridge ফিরলে মেসেজ পোল হয়ে যায়।

---

### L4 — + Hermes এজেন্ট ও MCP টুল লেয়ার (শুধু দরকার হলে)

দুটো আলাদা রিপো/সার্ভিস, দুটোই ঐচ্ছিক:

**ক) `hermes-runner`** — Core-এর `HERMES <request>` WhatsApp রিলে এবং
কাস্টমার-ডিসপ্যাচ ব্যাকএন্ড।

```env
HERMES_RUNNER_URL=http://127.0.0.1:8093
HERMES_RUNNER_SECRET=<অ্যাডমিন grant সিক্রেট>
HERMES_RUNNER_CUSTOMER_SECRET=<আলাদা কাস্টমার ডিসপ্যাচ সিক্রেট>
```

দুটো সিক্রেট **আলাদা রাখতেই হবে** (কোডে ইচ্ছাকৃতভাবে আলাদা)।
`HERMES_RUNNER_CUSTOMER_SECRET` ফাঁকা থাকলে কাস্টমার-ডিসপ্যাচ কখনো চালু হয় না —
fail-closed। একবারের আইডেন্টিটি সেটআপ: `scripts/create_hermes_mcp_admin.py`।

**খ) `fazle-mcp`** — MCP সার্ভার, যেটা Hermes/এজেন্টকে Core-এর টুল দেয়।

```bash
git clone https://github.com/arshiyaazim/fazle-mcp.git /home/azim/fazle-mcp
cd /home/azim/fazle-mcp
python3 -m venv venv && venv/bin/pip install -r requirements.txt
export FAZLE_CORE_API_KEY=<Core-এর INTERNAL_API_KEY>   # fazle_core_client.py এটাই পড়ে
venv/bin/python server.py                              # stdio MCP সার্ভার
```

তারপর এজেন্টের কনফিগে (`~/.hermes/config.yaml`) `mcp_servers.fazle-core` ব্লকে
সার্ভারটা পয়েন্ট করান। **মনে রাখুন:** `fazle-mcp` যেকোনো write tool
(ড্রাফট অ্যাপ্রুভ, send) চালানোর সময় Core-এর নিজের RBAC + `X-Internal-Key`
যাচাই আবার হয় — এজেন্ট সেটা বাইপাস করতে পারে না।

---

## ৩. পোর্ট ম্যাপ (এক নজরে)

| পোর্ট | সার্ভিস | বাধ্যতামূলক |
|---|---|---|
| 8200 | fazle-core (FastAPI + ড্যাশবোর্ড) | ✅ |
| 5432 | PostgreSQL | ✅ |
| 6379 | Redis | ⚪ |
| 11434 | Ollama | ⚪ |
| 8082 / 8081 / 8083 | Bridge1 / Bridge2 / Bridge3 | ⚪ (WhatsApp এর জন্য ✅) |
| 8093 | hermes-runner | ⚪ |
| 20128 / 20129 | OmniRoute / 9Router | ⚪ |
| 8090 | media processor | ⚪ |
| 6333 | Qdrant | ⚪ |
| 3000 | LocationWhere | ⚪ |

সব সার্ভিস **loopback (`127.0.0.1`)**-এ রাখুন; পাবলিক TLS শুধু Nginx-এ।

---

## ৪. `app/config.py` — কোন ভেরিয়েবল কোথায়

`DATABASE_URL` ছাড়া **প্রতিটা সেটিংসের ডিফল্ট আছে**, তাই `.env` ছোট রাখলেও
অ্যাপ চলে। দরকার হলে সব কী `app/config.py`-এর `Settings` ক্লাসে দেখুন
(প্রায় ২০০টি)। `.env.example`-এ অপারেটরদের সবচেয়ে দরকারি গুলো কমেন্টসহ আছে।

---

## ৫. যাচাই ও ট্রাবলশুটিং

### অটো-চেক

```bash
bash scripts/check_stack.sh          # সবই দেখায়
bash scripts/check_stack.sh --core   # শুধু বাধ্যতামূলক
```

স্ক্রিপ্টটা কিছুই চালু/বদলায় না — শুধু বলে কোনটা `OK`, কোনটা `absent`
(ঐচ্ছিক), আর কোনটা `REQUIRED-FAIL`। `REQUIRED-FAIL` থাকলে exit code = 1।

### হাতে যাচাই

```bash
curl -fsS http://127.0.0.1:8200/health | python3 -m json.tool   # 200 হলে ভালো, 503 = degraded
curl -fsS http://127.0.0.1:11434/api/tags                        # Ollama
curl -fsS http://127.0.0.1:8082/health                           # bridge1
pg_isready -h 127.0.0.1 -p 5432                                  # Postgres
redis-cli ping                                                   # Redis (ঐচ্ছিক)
```

### সাধারণ সমস্যা

| লক্ষণ | কারণ | সমাধান |
|---|---|---|
| স্টার্টআপেই `asyncpg`/connection error | Postgres নেই বা `DATABASE_URL` ভুল | DB চালু করুন, DSN ঠিক করুন, `pg_isready` |
| `ModuleNotFoundError: yaml / apscheduler` | নতুন venv-এ deps অসম্পূর্ণ | `pip install -r requirements.txt` |
| টেবিল নেই / `relation does not exist` | মাইগ্রেশন চালানো হয়নি | `.venv/bin/python db/migrate.py` |
| ড্যাশবোর্ড ৪০৩ | API key মেলেনি | `INTERNAL_API_KEY` আর localStorage-এর key এক করুন |
| রিপ্লাই সব সময় fallback টেক্সট | কোনো AI প্রোভাইডার নেই | Ollama চালু + `ollama pull hermes3:3b` |
| `[send-control] startup enable skipped` | `OUTBOUND_ENABLED` true নয় | ইচ্ছাকৃত safe mode — পাঠাতে চাইলে সচেতনভাবে true করুন |
| bridge পোল হচ্ছে না | `BRIDGE*_DB_PATH` ভুল/অপাঠ্য | `check_stack.sh`-এর `bridgeN_db` লাইন দেখুন |
| `/health` 503 | DB বা সাব-সিস্টেম degraded | `/health/deep` (key দিয়ে) কল করে বিস্তারিত দেখুন |

---

## ৬. নিরাপত্তা ও প্রোডাকশন নিয়ম

- `.env` → `chmod 600`, কখনো git-এ নয় (`.gitignore`-এ আছে)।
- `INTERNAL_API_KEY` শুধুই শক্ত র‍্যান্ডম স্ট্রিং; প্রতি অ্যাডমিনের আলাদা key দিলে
  RBAC (`fazle_admins`) কাজ করে।
- `OUTBOUND_ENABLED=false`, `AUTO_REPLY_ENABLED=false` — যতক্ষণ না পুরো চেইন
  যাচাই হয়েছে। ড্রাফট (`DRAFT_CREATION_ENABLED=true`) তখনো তৈরি হবে, শুধু
  পাঠানো হবে না — অ্যাডমিন `APPROVE` না দিলে কিছুই বেরোবে না।
- প্রোডাকশন `DATABASE_URL` / `.env` কখনো টেস্ট কমান্ডে ব্যবহার করবেন না;
  টেস্টের জন্য `TEST_DATABASE_URL` আলাদা রাখুন (`make test-unit`)।
- সব বাইরের সার্ভিস loopback-এ; পাবলিক এক্সপোজার শুধু Nginx TLS দিয়ে।
- মাইগ্রেশন কখনো প্রোডাকশনে ব্যাকআপ ছাড়া চালাবেন না — `RECOVERY.md` দেখুন।

---

## ৭. সবচেয়ে ছোট “সম্পূর্ণ কার্যকরী” কম্বো

যদি লক্ষ্য হয় **নিজের মেশিনে পুরো অ্যাপ ঘুরছে, WhatsApp পড়ছে-লিখছে, আর লোকাল
মডেল রিপ্লাই দিচ্ছে** — কিন্তু এজেন্ট লাগবে না:

```
PostgreSQL + fazle-core(.env, INTERNAL_API_KEY) + Ollama(hermes3:3b) + ৩টি bridge
```

MCP সার্ভার (`fazle-mcp`) আর `hermes-runner` — এগুলো পরে যখন এজেন্ট দিয়ে
অটোমেশন চালাতে চাইবেন তখনই যোগ করবেন। এগুলো ছাড়াই অ্যাপ ১০০% নিজের কাজ
(ইনজেস্ট → আইডেন্টিটি → রাউটিং → ড্রাফট → রিভিউ → পে-রোল/এসকর্ট) করে।
