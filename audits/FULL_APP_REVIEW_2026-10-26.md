# পূর্ণ অ্যাপ পর্যালোচনা — ২০২৬-১০-২৬

**প্রশ্ন:** পুরো অ্যাপ পর্যালোচনা করে দেখুন, সব ফাংশন কাজ করছে কিনা।

**পদ্ধতি:** অনুমান নয়, পরিমাপ। (ক) সব মডিউল আমদানি, (খ) সব রুট রিজলভ, (গ) অ্যাপ বাস্তবে চালিয়ে ২১০টি GET এন্ডপয়েন্ট ডাকা, (ঘ) ৪,১১৭ টেস্টের স্যুট, (ঙ) স্ট্যাটিক বিশ্লেষণ।

---

## ১. সারাংশ

| পরীক্ষা | ফলাফল |
|---|---|
| মডিউল আমদানি | **৭৭/৭৭** ✅ |
| FastAPI রুট রিজলভ | **৪০৭/৪০৭** ✅ (০ unresolved handler) |
| GET এন্ডপয়েন্ট (লাইভ, ২১০টি) | **১৭৫ × ২০০**, ২১ × ৪০৪, ৪ × ৪০০, ২ × ৪২২, ২ × ৪০৩, **৬ × ৫xx** |
| টেস্ট স্যুট (unit+integration+db+workflows+resilience) | **৪,১১৭ টেস্ট, ৩,৮১২ পাস = ৯২.৬%** |
| SQL ⇄ স্কিমা কনফর্মেন্স | **৩০/৩০ পাস** ✅ |
| pyflakes (প্রোডাকশন কোড) | ২০৫ সতর্কতা — কোনো **অসংজ্ঞায়িত নাম নেই** |
| e2e (Playwright) | যাচাইযোগ্য নয় — ব্রাউজার ইনস্টল করা যায়নি (নেটওয়ার্ক ব্লকড) |

**মূল কথা:** অ্যাপটি বুট হয়, সব মডিউল লোড হয়, রুটগুলো রিজলভ হয়, এবং ৯২.৬% টেস্ট পাস করে। তবে **২টি আসল কোড-ত্রুটি** পাওয়া গেছে যা নির্দিষ্ট এন্ডপয়েন্ট নষ্ট করে।

---

## ২. নিশ্চিত আসল ত্রুটি (কোডে)

### 🔴 ২.১ `/observability/summary` — যেকোনো ট্রাফিকেই ৫০০

**উপসর্গ:** `KeyError: 'count'` at `app/main.py:6029`

**মূল কারণ:** একই ধারণার **দুটি ভিন্ন বাস্তবায়ন**, যাদের হিস্টোগ্রাম-গঠন এক নয়:

| বাস্তবায়ন | সংরক্ষণ করে |
|---|---|
| `modules/observability/__init__.py:60-75` | `h["count"]`, `h["sum"]`, `h["buckets"]` |
| `app/main.py:84-124` (নিজস্ব `_InMemoryObservability`) | `{"labels": …, "value": …}` |

`observability_summary()` ব্যবহার করে main.py-এর নিজস্ব ক্লাস (`obs`, লাইন ১২৪), কিন্তু পড়তে চায় `d["count"]` ও `d["sum_ms"]` — **অন্য মডিউলের গঠন**। (এমনকি `modules/observability`-এর বিপরীতেও `sum_ms` ভুল; সেখানে নাম `sum`।)

**প্রমাণ (বিচ্ছিন্ন পুনরুৎপাদন):**
```
fresh (no traffic): count=0   -> 200 OK (বাগ লুকানো)
after 1 request:    samples=[{'labels': {...}, 'value': 12.3}]
                    ❌ KeyError: 'count'
correct form:       count=1, sum=12.3
```

**কেন বিপজ্জনক:** সার্ভার সদ্য চালু হলে এটি ২০০ দেয় — তাই স্টার্টআপ-স্মোকে ধরা পড়ে না। **একটিও HTTP অনুরোধ এলেই** স্থায়ীভাবে ৫০০।

**সমাধান:** `total_count = len(durs)` / `total_sum = sum(d["value"] for d in durs)`; অথবা `modules/observability`-এর অভিন্ন বাস্তবায়নে একীভূত করা।

---

### 🟠 ২.২ `/backup/status` — কোনো এরর-হ্যান্ডলিং নেই

**উপসর্গ:** `PermissionError: [Errno 13] Permission denied: '/home/azim'` (৫০০)

**মূল কারণ:** `modules/backup/__init__.py:47`
```python
base = Path(os.getenv("BACKUP_DIR", "/home/azim/backups"))
```
`_backup_dir()` (লাইন ৫০) `mkdir(parents=True)` চালায়। পথ অন্য মেশিনে অনুপস্থিত/অননুমোদিত হলে `api_backup_status()` (main.py:4249) কোনো try/except ছাড়াই ক্র্যাশ করে → ৫০০।

**মন্তব্য:** ডিফল্ট পথ `BACKUP_DIR` env দিয়ে ওভাররাইডযোগ্য, তাই প্রোডাকশন VPS-এ (`/home/azim`) সম্ভবত ঠিক চলে। কিন্তু **যেকোনো ফাইলসিস্টেম-ত্রুটিতে হ্যান্ডলারটি ৫০০ ফেরত দেয়** — একটি ব্যাকআপ-স্ট্যাটাস এন্ডপয়েন্টের জন্য অগ্রহণযোগ্য ভঙ্গুরতা।

---

### 🟠 ২.৩ `owner_contact_registry` — মালিকের পরিচিতি-সুরক্ষা গেটটি **ফেল-ওপেন**

(আগের ধাপে প্রমাণিত; এখানে অন্তর্ভুক্ত কারণ এটি পর্যালোচনার আওতাভুক্ত)

`modules/owner_contact_registry/__init__.py:48`:
```python
_REPO_ROOT = "/home/azim/core"      # হার্ডকোডেড, env দিয়ে ওভাররাইডযোগ্য নয়
```

**প্রমাণ:**
```
CSV exists?   = False
registry_size = 0
is_owner_managed_contact('01848144841') = False   ← CSV-এর প্রথম নম্বর!
OWNER_CONTACT_REGISTRY_ERROR … Falling back to NO CONTACT SUPPRESSION
```

যেকোনো ডেপ্লয়মেন্টে যেখানে রিপো `/home/azim/core`-এ নেই, মালিকের ব্যক্তিগত পরিচিতির (পরিবার, অফিস) জন্য **কোনো সুরক্ষা থাকে না**।

---

## ৩. ধরাবাঁধা ঝুঁকি: হার্ডকোডেড অ্যাবসোলিউট পাথ

প্রোডাকশন কোডে **৪৭টি** `/home/...` পাথ। শ্রেণিবিভাগ:

- **env-ওভাররাইডযোগ্য (গ্রহণযোগ্য):** `app/config.py`-এর ৬টি (pydantic-settings, `.env` দিয়ে বদলানো যায়), `BACKUP_DIR` (backup, scheduler)
- **ওভাররাইডযোগ্য নয় (সমস্যা):**
  - `app/main.py:5566` `_VOICE_UPLOAD_DIR`
  - `app/main.py:5660` `_UPLOAD_TEMP_DIR`
  - `modules/kb_upload/routes.py:26-27`
  - `modules/dispatch/routes.py:453`
  - `modules/owner_contact_registry/__init__.py:48` ← উপরে দেখুন
- **ডিবাগ-অবশেষ (মুছে ফেলা উচিত):** `modules/escort_roster/routes.py:388, 526, 555` — একটি নির্দিষ্ট ফোন-নম্বর (`01880446111`) সম্বলিত কনভার্সেশন-ফাইল ডিফল্ট হিসেবে, এবং কনফিগে `bridge2_db_path` থাকা সত্ত্বেও সরাসরি হার্ডকোডেড `bridge2_db`
- **মিথ্যা পজিটিভ:** `modules/contact_sync/__init__.py:45,48` (মন্তব্য মাত্র), `draft_quality`/`reviewed_reply_memory` (ইচ্ছাকৃত পাথ-ডিনাইলিস্ট)

---

## ৪. প্রত্যাহার — যেগুলো ত্রুটি **নয়**

পর্যালোচনার মাঝে আমি নিচের দুটিকে প্রোডাকশন বাগ হিসেবে শনাক্ত করেছিলাম; **তা ভুল**, নিচের প্রমাণের ভিত্তিতে প্রত্যাহার করছি।

### ❌ `/health` → ৫০৩ (`column "service" does not exist`)
### ❌ `/api/wa/contacts/{phone}` → ৫০০ (`column "last_seen" does not exist`)

**কেন ভুল ছিল:** দুটিই `tests/conftest.py`-এর **ফিক্সচার-স্কিমা** থেকে উদ্ভূত, কোড থেকে নয়।

| টেবিল | মাইগ্রেশন (প্রামাণ্য) | conftest (অনুমান) | কোড |
|---|---|---|---|
| `fazle_service_heartbeats` | `service` (০২৯:২৫৬) | `service_name` | `service` ✅ |
| `fazle_contacts` | `last_seen` আছে (০২৯:১৯২) | অনুপস্থিত | `last_seen` ✅ |

মাইগ্রেশন ০২৯-এর নিজস্ব হেডারেই সতর্কতা:
> "24 tables that exist in production but have no CREATE TABLE anywhere in this repo **except a guessed reconstruction in tests/conftest.py (already known to disagree with production)**"

আরও নিশ্চয়তা: `tests/unit/test_sql_column_conformance.py` (মাইগ্রেশন বনাম কোড) **৩০/৩০ পাস** করে।

**অতএব:** প্রোডাকশনে (যেখানে মাইগ্রেশন ০২৯ প্রযোজ্য) এই দুটি এন্ডপয়েন্ট ঠিকমতো কাজ করে। আমার স্যান্ডবক্সের DB conftest-এর অনুমান থেকে তৈরি, তাই সেখানে ব্যর্থ।

### ❌ `/admin/kb/list` → ৫০০ (`CharacterNotInRepertoireError: 0xe0 0xa6`)
কারণ আমার টেস্ট DB `SQL_ASCII` এনকোডিং-এ তৈরি হয়েছিল (UTF8 নয়) — বাংলা মাল্টি-বাইট টেক্সট তাই ব্যর্থ। **UTF8 DB-তে পুনরায় চালালে সুস্থ (২০০)।** আমার স্যান্ডবক্স-ত্রুটি।

### ❌ e2e ২২২টি এরর
`Executable doesn't exist` — Playwright ব্রাউজার অনুপস্থিত; `playwright install chromium` নেটওয়ার্ক-ব্লকড। **যাচাইযোগ্য নয়**, অ্যাপ-ত্রুটি নয়।

---

## ৫. টেস্ট-স্যুট স্বাস্থ্য

```
tests/unit + integration + db + workflows + resilience
  tests=4117   PASSED=3812 (92.6%)   failed=263   errors=31   skipped=11
```

**২৯৪টি ব্যর্থতার কারণ-ভিত্তিক বিভাজন:**

| কারণ | সংখ্যা | সম্ভাব্য উৎস |
|---|---|---|
| Assertion (লজিক) | ১৬৪ | মিশ্র — টেস্ট ও অ্যাপ |
| KeyError | ৪০ | বেশিরভাগ টেস্ট-হার্নেস (মক/ক্যাপচার্ড ডিকশনারি) |
| AttributeError | ৩৫ | বেশিরভাগ টেস্ট-হার্নেস (`'NoneType' has no attribute 'kwargs'`) |
| FileNotFoundError (হার্ডকোডেড পাথ) | ১৭ | টেস্ট-ডেটা পাথ (`/home/azim/core/...`) |
| অন্যান্য | ১৬ | — |
| DB/নেটওয়ার্ক সংযোগ | ৮ | পরিবেশ |
| Timeout | ৫ | ৯Router sqlite পাথ |
| SQL: কলাম নেই | ৪ | **ফিক্সচার-ড্রিফট** (মাইগ্রেশনে আছে) |
| SQL: টেবিল নেই | ৩ | **ফিক্সচার-ড্রিফট** (`fazle_roles` মাইগ্রেশন ০২৯-এ আছে) |
| TypeError | ২ | — |

**মন্তব্য:** সংখ্যাগরিষ্ঠ ব্যর্থতা টেস্ট-হার্নেসে (মক, ফিক্সচার, হার্ডকোডেড টেস্ট-পাথ), অ্যাপ-লজিকে নয়। তবে ১৬৪টি assertion-ফেল আলাদাভাবে ত্রায়াজ করা হয়নি — সেখানে অ্যাপ-ত্রুটি থাকতে পারে।

**একটি সংগ্রহ-ত্রুটি:** `tests/unit/test_phase_a_corpus.py` — `/home/azim/core/tests/.../corpus_meta.json` হার্ডকোডেড।

---

## ৬. সুপারিশ (অগ্রাধিকার ক্রমে)

1. **`/observability/summary` ঠিক করুন** — নিশ্চিত বাগ, সবচেয়ে সস্তা সমাধান, বর্তমানে ৫০০।
2. **`owner_contact_registry._REPO_ROOT` `__file__` থেকে বের করুন** — ফেল-ওপেন গোপনীয়তা-গেট; ২ লাইনের পরিবর্তন।
3. **`/backup/status`-এ try/except যোগ করুন** — ফাইলসিস্টেম-ত্রুটিতে ৫xx-এর বদলে একটি ত্রুটি-অবস্থা ফেরত দিক।
4. **হার্ডকোডেড পাথগুলো `__file__`/env থেকে বের করুন** — ৪৭টি; অন্তত ৫টি ওভাররাইডযোগ্য নয়।
5. **`escort_roster/routes.py`-এর ডিবাগ-অবশেষ মুছুন** (লাইন ৩৮৮, ৫২৬, ৫৫৫)।
6. **conftest-এর ফিক্সচার-স্কিমা মাইগ্রেশনের সাথে মেলান** — এটি বর্তমানে মাইগ্রেশনের সাথে দ্বিমত পোষণ করে এবং ভুয়া ব্যর্থতা তৈরি করে (৪টি SQL-ফেল + আমার মধ্যবর্তী ভুল সিদ্ধান্তের কারণ)।
7. **e2e একটি ব্রাউজার-সম্বলিত পরিবেশে চালান** — এই স্যান্ডবক্সে সম্ভব নয়।

---

## ৭. এই পর্যালোচনায় ব্যবহৃত প্রমাণ-কৌশল

- লাইভ সার্ভার: `DATABASE_URL=postgresql://…@127.0.0.1:55432/test INTERNAL_API_KEY=… uvicorn app.main:app`
- GET স্মোক: OpenAPI থেকে সব পাথ নিয়ে, `{param}` → `1`, বাধ্যতামূলক query-param সরবরাহ করে
- অথেন্টিকেশন: হেডার `X-Internal-Key` (`app/main.py:216`)
- **DB অবশ্যই UTF8 হতে হবে** — `SQL_ASCII` হলে বাংলা টেক্সট `CharacterNotInRepertoireError` দেয় এবং ভুয়া ৫০০ তৈরি করে
- conftest শুধু এই DB-নামগুলোতে স্কিমা তৈরি করে: `fazle_test`, `fazle_test_db`, `test`

*কোডে কোনো পরিবর্তন করা হয়নি — এটি একটি পর্যালোচনা-প্রতিবেদন মাত্র।*
