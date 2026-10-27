# লোকাল AI + pg_trgm সেটআপ — বন্ধ নেটওয়ার্কে (এয়ার-গ্যাপড) পদ্ধতি

**তারিখ:** ২০২৬-১০-২৭ · **প্রেক্ষাপট:** রেস্ট্রিক্টেড ইগ্রেস sandbox/production যেখানে
শুধু GitHub আর PyPI-তে পৌঁছানো যায় — `ollama.com`, `registry.ollama.ai`,
`huggingface.co`, GitHub release assets (`release-assets.githubusercontent.com`)
সব ব্লকড।

সাধারণ সার্ভারে আপনি সোজা `curl -fsSL https://ollama.com/install.sh | sh` আর
`ollama pull hermes3:3b` করবেন। যেখানে সেটা অসম্ভব, সেখানে এই ডকুমেন্টের পথে
**একই দুটি Ollama এন্ডপয়েন্ট** (`/api/tags`, `/api/generate`) জীবন্ত করা যায়,
যেগুলো `app/ollama_daemon.py` আদৌ ব্যবহার করে।

---

## ১. pg_trgm (মাইগ্রেশন ০২৩ ও ০২৯-এর জন্য বাধ্যতামূলক)

কেন লাগে: `023` আর `029` `gin_trgm_ops` ইনডেক্স বানায়; এক্সটেনশন না থাকলে ওই
স্টেটমেন্ট ফেলে, `029`-এর বাকি অংশ (যেমন `fazle_outbound_queue`) তৈরি না-ও হতে
পারে, আর `/health` critical দেখায়।

**সাধারণ সার্ভারে (সহজ পথ):**

```bash
sudo apt install postgresql-contrib-16
sudo -u postgres psql -d fazle_core -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

**এয়ার-গ্যাপড / vendored PostgreSQL (pgserver ইত্যাদি) হলে — সোর্স থেকে বিল্ড:**
headers + PGXS + gcc লাগে (pgserver-এ থাকে)।

```bash
# ১) PostgreSQL সোর্স (GitHub mirror; codeload অনুমোদিত)
curl -sL -o pg.tar.gz https://codeload.github.com/postgres/postgres/tar.gz/refs/tags/REL_16_2
tar xzf pg.tar.gz postgres-REL_16_2/contrib/pg_trgm
cd postgres-REL_16_2/contrib/pg_trgm

# ২) ঠিক যে PostgreSQL-এ ইনস্টল করবেন তার pg_config
PGCONFIG=/path/to/pginstall/bin/pg_config

make USE_PGXS=1 PG_CONFIG=$PGCONFIG
make USE_PGXS=1 PG_CONFIG=$PGCONFIG install

# ৩) সার্ভার রিস্টার্ট করে এক্সটেনশন তৈরি
psql -d fazle_core -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
psql -d fazle_core -c "SELECT similarity('escort program','escort programmes');"   # 0.7368…
```

এই স্যান্ডবক্সে ঠিক এভাবেই করা হয়েছে — `pg_trgm 1.6` ইনস্টল হয়েছে, এবং
আগে ব্যর্থ হওয়া তিনটি ইনডেক্স (`idx_fpe_emp_name_trgm`,
`idx_fpe_emp_name_norm_trgm`, `idx_fazle_employees_legacy_name_trgm`) এখন
তৈরি হয়েছে।

> ⚠️ ভুল ভার্সনের `pg_config` দিলে `.so` তৈরি হবে কিন্তু লোড হবে না। সবসময়
> সার্ভারের নিজের `bin/pg_config` ব্যবহার করুন।

---

## ২. লোকাল মডেল (≤ ১.৫ গিবি)

### ২.ক সাধারণ সার্ভারে — আসল Ollama (সুপারিশকৃত)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b      # ~986 MB  (বাংলা-সহ বহুভাষিক, ১.৫ GiB-র নিচে)
# অথবা: ollama pull llama3.2:1b   # ~1.3 GB
# অথবা: ollama pull hermes3:3b    # ~2 GB — অ্যাপের ডিফল্ট, কিন্তু সীমার বেশি
```

`.env`-এ: `OLLAMA_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=qwen2.5:1.5b`

### ২.খ এয়ার-গ্যাপড — PyPI থেকে GGUF + llama.cpp

PyPI-তে ছোট GGUF মডেল পাওয়া যায় `gemma3-270m-q4-k-m-gguf` (৪টি শার্ডে ভাগ করা):

```bash
pip install gemma3-270m-q4-k-m-gguf \
            gemma3-270m-q4-k-m-gguf-part1 gemma3-270m-q4-k-m-gguf-part2 \
            gemma3-270m-q4-k-m-gguf-part3 gemma3-270m-q4-k-m-gguf-part4

python - <<'PY'
import gemma3_270m_q4_k_m_gguf as g
out = g.assemble("/home/user/fazle-local/models/gemma-3-270m-q4_k_m.gguf")
print(out)          # sha256 নিজেই যাচাই করে: a5fd3b62…6818
PY
```

ফল: **241 MiB** (২৫৩,১১৩,০২৪ বাইট) — ১.৫ GiB সীমার অনেক নিচে।

রানটাইম (সোর্স থেকে কম্পাইল, ~৫ মিনিট, ২ কোর):

```bash
pip install cmake ninja
CMAKE_ARGS="-DGGML_NATIVE=ON -DLLAMA_CURL=OFF" pip install llama-cpp-python
```

---

## ৩. Ollama-সদৃশ লোকাল সার্ভার (`scripts/local_ollama_server.py`)

আসল Ollama বাইনারি নামানো না গেলে এই স্ক্রিপ্টটি `llama.cpp` দিয়ে ঠিক সেই
এন্ডপয়েন্টগুলো দেয় যা Fazle Core ডাকে:

| এন্ডপয়েন্ট | ব্যবহারকারী |
|---|---|
| `GET /api/tags` | `app/ollama.check_ollama_health()`, `/health`-এর `ollama` probe, `app/llm.py`-এর Hermes-পরিবার resolver |
| `POST /api/generate` | সব রিপ্লাই/ক্লাসিফাই/RAG কল (`response` ফিল্ড) |
| `POST /api/chat`, `/api/version`, `/api/ps`, `/api/show`, `POST /api/embeddings` (501) | বোনাস/স্পষ্ট ব্যর্থতা |

```bash
cd /home/user/fazle-core
.venv/bin/python scripts/local_ollama_server.py \
    --model-file /home/user/fazle-local/models/gemma-3-270m-q4_k_m.gguf \
    --model-name gemma3-270m \
    --host 127.0.0.1 --port 11434 --n-ctx 2048 --n-threads 2
```

`.env`-এ (নাম অবশ্যই `/api/tags`-এ দেখানো নামের সাথে মিলতে হবে):

```env
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3-270m
OLLAMA_RUNTIME_MODEL=gemma3-270m
OLLAMA_BUSINESS_MODEL=gemma3-270m
OLLAMA_MEMORY_MODEL=gemma3-270m
OLLAMA_GENERAL_MODEL=gemma3-270m
OLLAMA_DEEP_REASONING_MODEL=gemma3-270m
OLLAMA_INFER_CONCURRENCY=1
```

শিমটা যে মডেল-নামই চাওয়া হোক সেটাই সার্ভ করে (`--model-name` ফেরত দেয়), তাই
`OLLAMA_MODEL` মেলাতে ভুল হলে অ্যাপ ভাঙে না — কিন্তু `/health`-এ `active_model`
সঠিক দেখতে নাম মিলিয়ে রাখাই ভালো।

### যা এই শিম নয়

- মডেল পুল/ম্যানেজ করে না (কোনো `ollama pull` নেই), Modelfile নেই।
- GPU অফলোড পলিসি, KV-cache শেয়ারিং, সমবর্তী অনুরোধ — llama.cpp-এর নিজের
  আচরণ; এখানে একসাথে একটা অনুরোধ (lock), ঠিক যেমন অ্যাপের
  `OLLAMA_INFER_CONCURRENCY=1` ধরে নেয়।
- **আসল Ollama থাকলে আসল Ollama-ই চালান।** এটা ফলব্যাক।

---

## ৪. যাচাই

```bash
# শিম
curl -s http://127.0.0.1:11434/api/tags | python3 -m json.tool
curl -s -X POST http://127.0.0.1:11434/api/generate -H 'Content-Type: application/json' \
  -d '{"model":"gemma3-270m","prompt":"Hello","stream":false,"options":{"num_predict":8}}'

# অ্যাপ (আসল কোড-পথ দিয়ে, OmniRoute/Groq বাদ পড়ে Ollama-তে পৌঁছায়)
.venv/bin/python - <<'PY'
import asyncio
from app import llm
async def main():
    print(await llm.generate_reply(user_message="অফিস কখন খোলে?", intent="general"))
    print(llm.get_last_attempts())
asyncio.run(main())
PY

# হেলথ
curl -s -H "X-Internal-Key: $KEY" http://127.0.0.1:8200/health | python3 -m json.tool
```

এই স্যান্ডবক্সে বাস্তব ফল:

```
/health             → 200 "ok", probe ollama: ok, models: ["gemma3-270m"]
generate_reply      → attempts: omniroute=skipped_not_configured,
                                groq=skipped_not_configured,
                                ollama=success
```

---

## ৫. মডেল-মান সম্পর্কে সৎ কথা

241 MiB-র 270M মডেল **চলে, কিন্তু বাংলা রিপ্লাইয়ের মান দুর্বল** — পুনরাবৃত্তিমূলক
বাক্য তৈরি করে। প্রোডাকশনে যেটা চান:

| বাজেট | মডেল | আকার | মান |
|---|---|---|---|
| ≤ ১.৫ GiB | `qwen2.5:1.5b` | ~986 MB | ছোট কিন্তু ব্যবহারযোগ্য, বাংলা সাপোর্ট আছে |
| ≤ ১.৫ GiB | `llama3.2:1b` | ~1.3 GB | ইংরেজি ভালো, বাংলা মাঝারি |
| ≈ ২ GiB | `hermes3:3b` | ~2 GB | অ্যাপের ডিফল্ট, এজেন্ট-ধরনের কাজে সেরা |
| শুধু ডেমো/CI | `gemma3-270m` (এই ডক) | 241 MB | পাইপলাইন যাচাইয়ের জন্য, মান নয় |

`app/llm.py`-এর resolver ক্রম: `hermes3:3b` → `hermes3` → `hermes3:latest` →
`hermes` → `hermes:latest` → না পেলে `OLLAMA_MODEL`। তাই বড় সার্ভারে
`hermes3:3b` থাকলে সেটাই স্বয়ংক্রিয়ভাবে বেছে নেবে।

---

## ৬. এই সেটআপে যে রিপো-সংশোধন হলো

`tests/conftest.py`-এ `fazle_service_heartbeats` স্টাব কলামটির নাম ছিল
`service_name`, অথচ **কোডের সব জায়গা আর `db/migrations/029`-এর আসল টেবিল**
`service` ব্যবহার করে (`app/main.py::_probe_heartbeat`, `modules/scheduler`,
`modules/fazle_bridge_poller`, `modules/social_auto_reply/daemon_worker`)। ফলে
টেস্ট ডেটাবেসে প্রতিটি heartbeat probe আর heartbeat-নির্ভর টেস্ট
`column "service" does not exist`-এ ফেল করত। কলামের নাম `service` করা হয়েছে।

---

## ৭. একটা বাস্তব ফাঁদ যা এই সেশনে ধরা পড়ল

প্রিভিউ অ্যাপ আর pytest একই ডেটাবেস (`fazle_test`) ব্যবহার করছিল। pytest-এর
`pytest_configure` হুক প্রতিবার `DROP SCHEMA public CASCADE; CREATE SCHEMA
public;` চালায় — ফলে টেস্ট চালানোর সাথে সাথে চলমান অ্যাপের সব ডেটা (heartbeats
সহ) মুছে যায় এবং `/health` হঠাৎ `critical` দেখাতে শুরু করে।

নিয়ম: **অ্যাপের ডেটাবেস আর টেস্টের ডেটাবেস কখনো এক নয়।**

```env
DATABASE_URL=postgresql://…/fazle_core      # অ্যাপ
TEST_DATABASE_URL=postgresql://…/fazle_test # pytest
```

(README-র নিজের নিয়মও এটাই: “Never run production migrations or test commands
against the production database.”) `tests/conftest.py` শুধু `fazle_test`,
`test`, `fazle_test_db` নামে DROP করতে দেয় — নিরাপত্তা-গার্ড হিসেবে।
