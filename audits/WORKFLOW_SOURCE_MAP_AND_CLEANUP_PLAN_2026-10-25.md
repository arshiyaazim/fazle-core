# ওয়ার্ক-ফ্লো সোর্স-ম্যাপ, API যাচাই ও পরিচ্ছন্নতা পরিকল্পনা — ২০২৬-১০-২৫

**প্রশ্ন:** ৯টি ওয়ার্ক-ফ্লোর সোর্স কোথায়? এন্ড-টু-এন্ড ভেরিফাই, API এন্ডপয়েন্ট চেক, আর
অপ্রয়োজনীয় ফাইল/কোড সরিয়ে অ্যাপ হালকা করার প্লান।

**পদ্ধতি:** সম্পূর্ণ স্বয়ংক্রিয় স্ক্যান (AST-ভিত্তিক), হাতে-আন্দাজ নয়।
স্ক্রিপ্টগুলো রিপোর বাইরে: `/home/user/_wf_audit/` (`imports.py`, `routers.py`, `endpoints.py`)

> ⚠️ **এই ডকুমেন্টে কোনো ফাইল ডিলিট করা হয়নি।** সবকিছু প্রস্তাবনা — প্রতিটি ধাপ
> অনুমোদন সাপেক্ষে, এবং প্রতিটির জন্য rollback পথ আছে (git)।

---

## ১. সারাংশ

| বিষয় | ফলাফল |
|---|---|
| ৯টি ওয়ার্ক-ফ্লো | **সব ৯টিই LIVE** — সবকটির প্রোডাকশন কোডে কর্মক্ষম মডিউল আছে |
| API রাউটার | **২৩টি** সংজ্ঞায়িত → **২১টি মাউন্টেড** (২টি কখনোই মাউন্ট হয়নি) |
| HTTP এন্ডপয়েন্ট | **২৬০টি** রুট, ২১টি মাউন্টেড রাউটারে |
| রানটাইম স্মোক-টেস্ট | **২১/২১** মাউন্টেড রাউটার নির্ঘাতে ইমপোর্ট হয় |
| মৃত কোড | **৫০টি ইউনিট** প্রোডাকশনে অস্পৃষ্ট — তিন স্তরে ভাগ (নিচে) |
| ঘোষিত নয় এমন ডিপেন্ডেন্সি | **৬টি** (`yaml`, `openai`, `redis`, `apscheduler`, `imagehash`, `requests`) |

### স্কেল (প্রেক্ষাপট)

```
modules/    86,339 লাইন / 237 ফাইল
app/        10,801 লাইন /  16 ফাইল
shared/      7,340 লাইন /  27 ফাইল
scripts/     6,637 লাইন /  40 ফাইল
tests/      81,171 লাইন / 304 ফাইল   ← মডিউলের সমান!
docs/      100,708 লাইন (.md)        ← সবচেয়ে বড়
```

**মন্তব্য:** "হালকা করা"র বড় লিভার মৃত কোড (≈১,১০০ লাইন) নয় — বরং
**রুটের ৪৩টি ঐতিহাসিক অডিট-ডক (১৮,৫৩৪ লাইন)** ও সামগ্রিক ডক-ভলিউম।

---

## ২. ৯টি ওয়ার্ক-ফ্লো → সোর্স

প্রতিটির প্রোডাকশন ইমপোর্টার-সংখ্যা (prod / test) দেওয়া আছে — সবগুলোই LIVE।

| # | ওয়ার্ক-ফ্লো | প্রধান সোর্স মডিউল | prod | test |
|---|---|---|---:|---:|
| ১ | **Attendance** | `modules/attendance/`, `modules/attendance_parser/` | 6, 1 | 5, 0 |
| ২ | **Cash** | `modules/fazle_payroll_engine/`, `modules/payment_relay/`, `modules/payment_relay_accounting/`, `modules/financial_operations.py` | 36, 1, 3, 2 | 16, 2, 2, 2 |
| ৩ | **Client Order** | `modules/client_billing/`, `modules/conversation_layer/` | 2, 5 | 3, 5 |
| ৪ | **Escort** | `modules/escort/`, `modules/escort_lifecycle/`, `modules/escort_roster/`, `modules/escort_slip_extractor/` | 14, 6, 17, 3 | 17, 6, 8, 1 |
| ৫ | **Payment** | `modules/fazle_payment_workflow/`, `modules/fazle_payment_ingest/`, `modules/fazle_draft_approval/`, `modules/payment_correction/` | 7, 6, 3, 1 | 5, 3, 1, 3 |
| ৬ | **Recruitment** | `modules/recruitment_flow/`, `modules/recruitment_detector/`, `modules/recruitment_turn_decision/`, `modules/recruitment_authority.py`, `modules/recruitment_recovery_sweep/` | 14, 2, 8, 8, 1 | 30, 1, 6, 3, 2 |
| ৭ | **Release Slip** | `modules/escort_slip_extractor/`, `modules/ocr_processor/`, `modules/escort_lifecycle/` | 3, 3, 6 | 1, 0, 6 |
| ৮ | **Salary** | `modules/payroll/`, `modules/payroll_logic/`, `modules/fazle_payroll_engine/` | 7, 2, 36 | 6, 2, 16 |
| ৯ | **WhatsApp Reply** | `modules/message_router/`, `modules/route_b/`, `modules/route_b_handoff/`, `modules/outbound/`, `modules/conversation_state.py` | 17, 1, 1, 18, 1 | 31, 5, 4, 19, 2 |

**এন্ট্রি-পয়েন্ট বিন্দু:** ৯টিই `app/main.py` দিয়ে যুক্ত — না হয়
`include_router()`-এর মাধ্যমে (REST), না হয় ওয়েবহুক/পোলার পাথ
(`process_message()`, `start_pollers()`, `start_fpe()`)। কোনো ওয়ার্ক-ফ্লোই "অনাথ" নয়।

### ⚠️ ডক বনাম কোড ড্রিফট

`knowledge_base/05_workflows/escort_source_of_truth_workflow.md`
`modules/fazle_admin_commands.py` উল্লেখ করে — **এই ফাইলের অস্তিত্বই নেই**
(এটি একটি প্যাকেজ: `modules/fazle_admin_commands/`)।

আরও: ১০টি ওয়ার্ক-ফ্লো ডকের মধ্যে **মাত্র ৪টিতে** সোর্স-ফাইলের রেফারেন্স আছে।
বাকি ৬টিতে কোড-রেফারেন্স নেই — ডক পুরনো হলে তা ধরা পড়বে না।

---

## ৩. API এন্ডপয়েন্ট যাচাই

| মেট্রিক | মান |
|---|---|
| `APIRouter` সংজ্ঞা | ২৩ |
| `include_router()` কল (`app/main.py`) | ২১ |
| মোট HTTP রুট | **২৬০** |
| রাউটার ইমপোর্ট-টেস্ট | **২১/২১ পাস** |

### সবচেয়ে বড় রাউটার

| রাউটার | রুট সংখ্যা |
|---|---:|
| `modules/fazle_payroll_engine/routes.py` | ৫২ |
| `modules/escort_roster/routes.py` | ৩৫ |
| `modules/dispatch/routes.py` | ১৬ |
| `modules/client_billing/routes.py` | ১৫ |

### 🔴 কখনোই মাউন্ট হয়নি (এন্ডপয়েন্ট অপ্রবেশযোগ্য)

| ফাইল | অবস্থা |
|---|---|
| `modules/ollama_memory/memory_api.py` | রাউটার আছে, `include_router` নেই → কোনো এন্ডপয়েন্টই কল করা যায় না |
| `shared/realtime.py` | একই |

দুটিই **B2 স্তরের ডিলিট-প্রার্থী** (নিচে দেখুন)।

---

## ৪. এন্ড-টু-এন্ড ভেরিফিকেশন — যা করা গেছে ও যা **যায়নি**

### ✅ যাচাই করা গেছে

1. **ইমপোর্ট-গ্রাফ** — ৬৩৬টি পাইথন ফাইল AST দিয়ে পার্স; relative import
   (`from . import x`) সহ সমাধান করা হয়েছে। প্রথম পাসে ৬৩টি "মৃত" দেখালেও
   relative-import ঠিক করার পর **৪৭**-এ নামে — অর্থাৎ ১৬টি আগে ভুল পজিটিভ ছিল,
   সেগুলো আসলে জীবন্ত কোড।
2. **রানটাইম স্মোক-টেস্ট** — ২১টি মাউন্টেড রাউটার মডিউল আসলে ইমপোর্ট করে দেখা
   হয়েছে: **২১/২১ সফল**।
3. **ডাইনামিক-ইমপোর্ট অডিট** — `import_module()`-এর ৬১টি ব্যবহারের মধ্যে
   **৫৬টি স্ট্যাটিক শিম** (`_NEW = "modules.fazle_x"` ধাঁচের), আর
   **প্রোডাকশনে truly-dynamic ডিসপ্যাচ = ০** (বাকি ৫টিই টেস্টে)।
   → "কোথাও ইমপোর্ট নেই" এই সিদ্ধান্ত নির্ভরযোগ্য।

### ❌ যা যাচাই করা **যায়নি** (সততার খাতিরে)

- **কোনো ডেটাবেজ নেই** — স্যান্ডবক্সে PostgreSQL অনুপস্থিত (পোর্ট ৫৪৩৩ খালি)।
  তাই কোনো ওয়ার্ক-ফ্লোর **আসল রানটাইম প্রমাণ** দেওয়া যায়নি: আমি যাচাই করেছি
  "কোড পৌঁছানো যায় ও ইমপোর্ট হয়", যাচাই করিনি "সঠিক ফলাফল দেয়"।
- **HTTP লেভেল টেস্ট** — অ্যাপ বুট করতে DB লাগে, তাই ২৬০টি রুটের
  আসল রেসপন্স পরীক্ষা করা যায়নি।
- **বাহ্যিক কলার** — এই রিপোর বাইরে (যেমন `fazle-mcp`) কেউ পুরনো পাথ
  ইমপোর্ট করে কিনা, তা এই রিপো থেকে দেখা যায় না। **এটিই বড় ঝুঁকি** (§৬)।

---

## ৫. মৃত কোড — তিন স্তর

মোট **৫০টি ইউনিট** প্রোডাকশন কোডে স্পর্শ করে না। কিন্তু সবগুলো ডিলিট করা যাবে না:

### স্তর A — শিম (২৩ ফাইল, ১,০৯২ লাইন) — 🔒 **রাখুন**

২০২৬-১০-২১-এর `fazle_` প্রিফিক্স ইউনিফিকেশনের backward-compatibility শিম।
`tests/test_prefix_unification.py::test_old_module_path_is_a_deprecation_shim`
এগুলোর অস্তিত্ব **বাধ্যতামূলক** করে — ডিলিট করলে টেস্ট ফেল করবে।

```
modules/admin_commands/*          -> modules/fazle_admin_commands/*
modules/bridge_poller/            -> modules/fazle_bridge_poller/
modules/draft_approval/           -> modules/fazle_draft_approval/
modules/identity_brain/           -> modules/fazle_identity_brain/
modules/image_hash/               -> modules/fazle_image_hash/
modules/intent/                   -> modules/fazle_intent/
modules/media_normalization/      -> modules/fazle_media_normalization/
modules/message_archive/          -> modules/fazle_message_archive/
modules/payment_ingest/           -> modules/fazle_payment_ingest/
modules/payment_workflow/         -> modules/fazle_payment_workflow/
modules/group_identity.py         -> modules/fazle_group_identity.py
modules/identity_resolver.py      -> modules/fazle_identity_resolver.py
```

### স্তর B1 — মৃত, কিন্তু **শিমের টার্গেট** (৬ ফাইল, ১,১৯৬ লাইন) — ⚠️ একসাথে সরাতে হবে

| ফাইল | লাইন | কারণ |
|---|---:|---|
| `modules/fazle_admin_commands/nl_payments.py` | ৩৮৬ | `admin_commands/nl_payments.py` শিম একে পয়েন্ট করে |
| `modules/fazle_data_sync/__init__.py` | ২৩১ | `payment_ingest/wbom_fpe_sync.py` শিমের টার্গেট |
| `modules/fazle_admin_commands/nl_outbound.py` | ১৮০ | শিম টার্গেট |
| `modules/fazle_message_archive/__init__.py` | ১৫৪ | `message_archive` শিমের টার্গেট |
| `modules/fazle_admin_commands/nl_employee_stats.py` | ১৩৭ | শিম টার্গেট |
| `modules/fazle_admin_commands/nl_search.py` | ১০৮ | শিম টার্গেট |

> এগুলো সরাতে হলে **সংশ্লিষ্ট শিম + `MODULE_RENAMES` এন্ট্রি + টেস্ট** —
> তিনটিই একসাথে বদলাতে হবে। এটি একটি সমন্বিত সিদ্ধান্ত, কসমেটিক ক্লিনআপ নয়।

### স্তর B2 — মৃত, কোনো শিম-সম্পর্ক নেই — ✅ সরানো যায়

> **সংশোধন (২০২৬-১০-২৫, ডিলিট-পূর্ব যাচাইয়ে):** প্রথম খসড়ায় `shared/realtime.py`-কে
> এখানে রাখা হয়েছিল — **এটি ভুল**। ঐ ফাইলের *রাউটার* অমাউন্টেড হলেও *মডিউলটি* LIVE
> (`app/main.py:360` `start_event_bridge()`, `diagnostics.py`, `frontend_sync.py`,
> `self_heal.py`)। তাই এটি **রাখা হচ্ছে**। একই যাচাইয়ে আরও ৩টি ফাইল পাওয়া গেছে
> যেগুলোর **টেস্ট-রেফারেন্স আছে** — সেগুলো HELD (নিচে)। নিচের যাচাইয়ে
> `memory_models.py`-ও একই মৃত ক্লাস্টারের অংশ বলে যোগ করা হয়েছে।

#### B2-a — সরানো হচ্ছে (১৯ ফাইল, ৭১৮ লাইন) ✅

| ফাইল | লাইন |
|---|---:|
| `modules/social_auto_reply/salary_flow.py` | ২৮৫ |
| `modules/fazle_payroll_engine/replay.py` | ১৬২ |
| `modules/operations_health/__init__.py` (পুরো প্যাকেজ) | ৪২ |
| `modules/social_auto_reply/service_runner.py` | ৩৭ |
| `modules/ollama_memory/memory_manager.py` | ৩৪ |
| `modules/recruitment_assistant/__init__.py` (পুরো প্যাকেজ) | ২৯ |
| `modules/ollama_memory/memory_models.py` (ক্লাস্টার) | ২৮ |
| `modules/ollama_memory/memory_api.py` ← **অমাউন্টেড রাউটার** | ২৭ |
| `modules/social_auto_reply/retry_queue.py` | ২২ |
| `modules/social_auto_reply/comment_handler.py` | ১৬ |
| `modules/ai_readonly_tools/*.py` (৯টি re-export wrapper) | ৩৬ |
| **মোট** | **৭১৮** |

*`modules/ollama_memory/__init__.py` LIVE (`app/main.py:5343`, `ai_console/live_adapters`) —
এটি ঐ ৩টি ফাইল ইমপোর্ট করে না, তাই প্যাকেজটি অক্ষত থাকবে।*

#### B2-b — HELD: মৃত কিন্তু **টেস্ট-সংযুক্ত** (৩ ফাইল, ৪০৮ লাইন) ⏸️

| ফাইল | লাইন | কেন রাখা হলো |
|---|---:|---|
| `modules/recruitment_ai/__init__.py` | ২৬৬ | `tests/unit/test_recruitment_ai_restricted.py` ৪টি সিম্বল ইমপোর্ট করে। রিপোর নিজের মন্তব্য: *"recruitment_ai has no live callers left"* — তবুও টেস্ট মুছতে হবে, তাই আপনার সিদ্ধান্ত |
| `modules/employee_privacy.py` | ১২০ | ২টি নিবেদিত টেস্ট; ডকস্ট্রিং-এ *"the CRITICAL PRIVACY RULE"*। নিরাপত্তা-সংক্রান্ত কভারেজ মুছা ঝুঁকিপূর্ণ |
| `modules/payment/__init__.py` | ২২ | `test_owner_contact_registry.py:237` স্পষ্টভাবে অ্যাসার্ট করে *"modules.payment must still import"* — ইচ্ছাকৃত গার্ড |

#### ❌ তালিকা থেকে সরানো হয়েছে

| ফাইল | কারণ |
|---|---|
| `shared/realtime.py` | **LIVE** — ৫টি প্রোডাকশন ইমপোর্টার (`start_event_bridge`, `get_realtime_stats` ×৩) |

> **পার্শ্ব-খুঁজে-পাওয়া (এখন ঠিক করা হয়নি):** `app/main.py:515`-এ
> `from shared.realtime import router as _realtime_router` — ইমপোর্ট করা হয়েছে কিন্তু
> **কখনো মাউন্ট করা হয়নি** ("Phase 12C — Realtime WebSocket endpoint")। অর্থাৎ ঐ
> WebSocket এন্ডপয়েন্ট অপ্রবেশযোগ্য। ইমপোর্ট-লাইনটি মুছলে কোড হালকা হবে, কিন্তু
> মাউন্ট করার ইচ্ছাটাও হারিয়ে যেতে পারে — তাই সিদ্ধান্ত আপনার।

---

## ৬. 🔴 আমার নিজের আগের কাজ সম্পর্কে সতর্কবার্তা

অডিটের §১.২-তে আমি `modules/fazle_admin_commands/nl_payments.py`-এর
`intent_employee_totals()` ঠিক করেছিলাম (ফোন কলাম + ক্রস-সিস্টেম ID ব্রিজ)।

**এই স্ক্যানে প্রমাণিত হয়েছে: ঐ ফাংশনটি প্রোডাকশনে কেউ কল করে না।**
একমাত্র কলার `tests/unit/test_nl_payments.py`। এটি স্তর **B1**-এ পড়ে।

- ফিক্সটি **ভুল ছিল না** — কোডটি কখনো প্রোডাকশনে ঢুকলে ঠিকভাবেই চলবে।
- কিন্তু এটি একটি **অপ্রবেশযোগ্য পথ** রক্ষা করছে। বাগটি টিকে গিয়েছিল ঠিক
  এ কারণেই: কেউ কলই করতো না, তাই ক্র্যাশও হতো না।
- এটি B1 তালিকার অন্য ৫টি ফাইলের ক্ষেত্রেও প্রযোজ্য — একই "nl_*" পরিবার,
  যা কখনো ওয়্যার-আপ হয়নি।

**প্রশ্ন আপনার:** `nl_payments`/`nl_search`/`nl_outbound`/`nl_employee_stats`
— এগুলো কি ভবিষ্যতের জন্য রাখা **অসমাপ্ত কাজ**, নাকি **পরিত্যক্ত**?
উত্তরের ওপর B1 সরানোর সিদ্ধান্ত নির্ভর করবে।

---

## ৭. ডিপেন্ডেন্সি ফাঁক (স্টার্টআপ-ব্রেকিং)

`requirements.txt`-এ নেই, অথচ কোডে ইমপোর্ট:

| প্যাকেজ | ব্যবহার | ঝুঁকি |
|---|---|---|
| **`yaml`** | `app/unified_routing.py` (`app/llm.py` লেজি-ইমপোর্ট করে) | 🔴 **অ্যাপ স্টার্টআপে ক্র্যাশ** — ফ্রেশ ইনস্টলে |
| `openai` | ৪টি ফাইল (`app/github_models.py` সহ) | 🟠 LLM পাথ |
| `redis` | ৩টি ফাইল | 🟠 ক্যাশ/স্টেট |
| `apscheduler` | `modules/scheduler/__init__.py` | 🟠 শিডিউলার |
| `imagehash` | `modules/fazle_image_hash/__init__.py` | 🟡 |
| `requests` | ২টি স্ক্রিপ্ট | 🟡 |

`yaml` বিশেষভাবে উল্লেখযোগ্য: `app/unified_routing.py` **মৃত নয়** —
`app/llm.py:177`-এ লেজি-ইমপোর্টের মাধ্যমে লাইভ। তাই এটি আসল সমস্যা।

*(`PIL`/`fitz`/`docx`/`dotenv`/`pydantic*`/`qdrant*`/`sentence_transformers`
স্ক্যানে "অঘোষিত" দেখালেও এগুলো ঘোষিত — শুধু প্যাকেজ-নাম ≠ ইমপোর্ট-নাম।)*

---

## ৮. ডকুমেন্টেশন — সবচেয়ে বড় "হালকা করার" সুযোগ

- রুটে **৪৩টি `.md`, ১৮,৫৩৪ লাইন**; এর **২১টিই** এককালীন
  AUDIT/PLAN/REPORT (`HERMES_*.md`, `payroll-escort-workflow-audit-*.md`, …)।
- `archive/historical-reports/AUDIT_REPORT.md` (৯৬১ লাইন) নিজেই শিরোনামে লিখেছে:
  *"⚠️ STALE — do not treat as current."*
- মোট `.md` = **১,০০,৭০৮ লাইন** — সবচেয়ে বড় অংশ।

**প্রস্তাব: ডিলিট নয়, `archive/`-এ সরান।** `archive/deprecated/` আগে থেকেই আছে।
ইতিহাস হারাবে না, রুট পরিষ্কার হবে।

---

## ৯. প্রস্তাবিত কর্মপরিকল্পনা (ধাপে ধাপে)

| ধাপ | কাজ | আনুমানিক লাভ | ঝুঁকি |
|---|---|---|---|
| **০** | `requirements.txt`-এ `PyYAML` যোগ | স্টার্টআপ ক্র্যাশ রোধ | ✅ নেই |
| **১** | B2-এর ২১টি ফাইল সরান | −১,০৯৮ লাইন | 🟢 নিম্ন — অমাউন্টেড রাউটার ২টিও এর মধ্যে |
| **২** | রুটের ২১টি ঐতিহাসিক `.md` → `archive/` | −~১০,০০০ লাইন (ডক) | 🟢 নিম্ন — git-এ ইতিহাস থাকে |
| **৩** | `escort_source_of_truth_workflow.md`-এর ভুল সোর্স-পাথ ঠিক | ডক সত্যতা | 🟢 নিম্ন |
| **৪** | বাকি ৫টি অঘোষিত ডিপেন্ডেন্সি যোগ | পূর্ণাঙ্গতা | 🟡 মধ্যম — `openai`/`redis` অপশনাল হতে পারে |
| **৫** | B1 + সংশ্লিষ্ট শিম একসাথে সরান | −১,১৯৬ লাইন | 🔴 **উচ্চ** — বাহ্যিক কলার যাচাই দরকার |
| **৬** | স্তর A-এর ২৩টি শিম সরান | −১,০৯২ লাইন | 🔴 **উচ্চ** — টেস্ট বদলাতে হবে + বাহ্যিক কলার |

### ধাপ ৫ ও ৬-এর পূর্বশর্ত

1. **বাহ্যিক কলার যাচাই** — `fazle-mcp` ও অন্য সার্ভিসে
   `modules.payment_workflow` / `modules.admin_commands` / `modules.intent`
   ইমপোর্ট আছে কিনা। এই রিপো থেকে দেখা যায় না।
2. রেনেম-এর পর যথেষ্ট সময় (২০২৬-১০-২১ → এখন ৪ দিন) পেরিয়েছে কিনা — সিদ্ধান্ত আপনার।

---

## ১০. সীমাবদ্ধতা

- সবকিছুই **স্ট্যাটিক বিশ্লেষণ** + ইমপোর্ট-স্মোক। কোনো ডিবি নেই →
  কোনো ওয়ার্ক-ফ্লোর **কার্যকরী** (functional) প্রমাণ নেই।
- "মৃত" = এই রিপোতে কোনো প্রোডাকশন ইমপোর্টার নেই। বাহ্যিক রিপো/রানটাইম
  মনকি-প্যাচ এই সংজ্ঞার বাইরে।
- স্ট্রিং-ভিত্তিক মডিউল রেফারেন্স (যেমন কনফিগ-ফাইলে প্লাগিন-পাথ) স্ক্যান করা হয়েছে —
  `resources/` ও `knowledge_base/`-এর JSON-এ শুধু **তথ্যসূত্র** হিসেবে কিছু পাথ আছে,
  কোড-রেফারেন্স নয়।
