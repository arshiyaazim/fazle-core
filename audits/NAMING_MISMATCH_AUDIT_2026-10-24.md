# নেমিং/কলাম-হেডার অমিল অডিট — ২০২৬-১০-২৪

**উদ্দেশ্য:** রিপোজিটোরির কোড, ডকস ও ডিবি-স্কিমা জুড়ে একই জিনিসের নাম একই আছে কিনা যাচাই করা।
বিশেষভাবে: **কোনো কলাম-হেড যদি অপর একটি টেবিলের (বা মাইগ্রেশন/কোড/ডকসের) সাথে না মিলে**।

**পদ্ধতি:** সম্পূর্ণ স্বয়ংক্রিয়, হাতে-বাছাই নয়।

1. রিপোর **সব ১২০টি `.sql` ফাইল** পার্স করে (৪টি আলাদা মাইগ্রেশন ডিরেক্টরি) ক্রমান্বয়ে
   `CREATE TABLE` / `ALTER TABLE ADD|DROP|RENAME COLUMN` / `ALTER TABLE RENAME TO` রিপ্লে করে
   একটি ক্যানোনিক্যাল স্কিমা বানানো হয়েছে → **১৩৫ টেবিল, ১,৬২৫ কলাম**।
2. **২৮০টি প্রোডাকশন `.py` ফাইল**-এর SQL স্ট্রিং লিটারেল AST দিয়ে বের করে, টেবিল-এলিয়াস
   রিজল্ভ করে প্রতিটি কলাম-রেফারেন্স ওই স্কিমার সাথে মেলানো হয়েছে।
3. `tests/conftest.py`-এর টেস্ট-ফিক্সচার স্কিমা ও **২৮৫টি মার্কডাউন ডক**-ও একইভাবে তুলনা করা হয়েছে।
4. লাইভ ডিবির সত্যিকারের অবস্থা `tools/prefix_objects.json` (pg ডাম্প) ও `db/migrations/029_*`-এর
   pg_dump-নির্ভর সংজ্ঞা দিয়ে ক্রস-চেক করা হয়েছে।

> অডিট স্ক্রিপ্টগুলো রিপোর বাইরে (`/home/user/_naming_audit/`) রাখা হয়েছে, যাতে রিপো ডার্টি না হয়।

---

## সারাংশ

| শ্রেণি | সংখ্যা | মারাত্মকতা |
|---|---:|---|
| 🔴 কোড যে কলাম পড়ছে/লিখছে, ডিবিতে সেই নামেই নেই (রানটাইম-ব্রেকিং) | **৭** | অবিলম্বে |
| 🟠 প্রোডাকশন টেবিল যার `CREATE TABLE` রিপোতেই নেই | **৪** | উচ্চ |
| 🟡 টেস্ট-ফিক্সচার (`conftest.py`) বনাম মাইগ্রেশন কলাম-হেডার অমিল | **২১ টেবিল** | উচ্চ (টেস্ট ভ্রান্ত আশ্বাস দেয়) |
| 🟣 টেবিল-নেমিং/মাইগ্রেশন-সিস্টেম অমিল | **৪** | মধ্যম–উচ্চ |
| ⚪ একই ধারণার জন্য ভিন্ন ভিন্ন কলাম-নাম (কনভেনশন ড্রিফট) | ৪০+ | নীতিগত |

---

# 🔴 শ্রেণি ১ — কোডের কলাম-নাম ডিবির সাথে মেলে না (রানটাইম-ব্রেকিং)

> প্রতিটি এন্ট্রি হাতে যাচাই করা হয়েছে। (`fazle_cash_transactions.reported_by_phone` একটি
> স্ক্যানার ফলস-পজিটিভ ছিল — সবগুলো সাইট আসলে `fpe_income_transactions`-এর, যেখানে সেই
> কলাম আছে; তাই তালিকা থেকে বাদ দেওয়া হয়েছে।)

এগুলো সরাসরি `asyncpg.exceptions.UndefinedColumnError` দেবে বা নীরবে ভুল ডেটা দেবে।

### ১.১ `wbom_salary_records` — কোড + ডকস + টেস্ট, সব একদিকে; ডিবি অন্যদিকে 🔴🔴

`modules/payroll_logic/__init__.py:131`

```sql
SELECT amount AS net_salary, status AS payment_status, payment_date
FROM wbom_salary_records
WHERE employee_id = $1 AND salary_month = $2
```

| উৎস | কলাম-নাম |
|---|---|
| **কোড** (`payroll_logic`) | `amount`, `status`, `salary_month` |
| **টেস্ট ফিক্সচার** (`tests/conftest.py:413`) | `record_id`, `salary_month`, `amount`, `status` |
| **ডক** (`docs/PRODUCTION_CERTIFICATION_v1.0.md:86`) | `amount` |
| **ডিবি** (`029_*`, লাইভ pg_dump থেকে) | `salary_id`, `employee_id`, `month`, `year`, `basic_salary`, `total_programs`, `program_allowance`, `other_allowance`, `total_advances`, `total_deductions`, `net_salary`, `payment_date`, `payment_status`, `remarks` |

**ফলাফল:** `amount`, `status`, `salary_month` — তিনটিই ডিবিতে **অস্তিত্বহীন**।
কোডটি `amount`-কে `net_salary` ও `status`-কে `payment_status` নামে **এলিয়াস** করছে — অর্থাৎ
লেখক জানতেন ডিবিতে সঠিক নাম `net_salary`/`payment_status`, কিন্তু ভুল টেবিল-স্কিমার বিপরীতে লিখেছেন।
এছাড়া ডিবিতে মাস আলাদা নয় — `month` + `year` দুটি কলাম, কিন্তু কোড `salary_month`-এ `'YYYY-MM'` পাঠাচ্ছে।

**নীরব কিনা:** হ্যাঁ, আংশিক। রিপোতে কেউ `wbom_salary_records`-এ INSERT/UPDATE করে না
(যাচাই করা হয়েছে) → টেবিল সবসময় ফাঁকা → `salary_rec` সবসময় `None` →
`under_review` সবসময় `True`। তাই বাগটি ক্র্যাশ না করে **চুপচাপ ভুল ফলাফল** দেয়।

`docs/PRODUCTION_CERTIFICATION_v1.0.md:86` নিজেই এই ড্রিফট স্বীকার করেছে:
> "`wbom_salary_records.amount`/`.created_at`/`.record_id` vs production's `.total_advances`/`.net_salary`/`.program_allowance` naming, suggesting a column rename happened in production that the migration files never picked up."

### ১.২ `fazle_cash_transactions.payment_mobile` + `fazle_employees.employee_mobile` 🔴

`modules/fazle_admin_commands/nl_payments.py:176` এবং `:307`

```python
where_phone = ("AND (t.payment_mobile = $3 OR t.payment_mobile = $4 "
               "     OR e.employee_mobile = $3 OR e.employee_mobile = $4)")
```

- `t` = `fazle_cash_transactions` → `payment_mobile` **নেই** (আছে `payout_phone`)
- `e` = `fazle_employees` → `employee_mobile` **নেই** (আছে `primary_phone`, `employee_id_phone`)

**দুর্বলতা:** ঠিক এই স্টেটমেন্টের SELECT-লিস্টে লেখক `t.payout_phone AS payment_mobile` ও
`e.primary_phone AS emp_mobile` এলিয়াস দিয়েছেন — কিন্তু WHERE-ক্লজে সেই **আউটপুট-এলিয়াসকেই**
`t.`/`e.` প্রিফিক্স দিয়ে ব্যবহার করেছেন। PostgreSQL-এ WHERE-এ আউটপুট-এলিয়াস বৈধ নয়, এবং
প্রিফিক্স থাকায় এটি টেবিল-কলাম হিসেবে রিজল্ভ হয় → `UndefinedColumnError`।
**ট্রিগার:** কোয়েরি টেক্সটে ফোন নাম্বার থাকলেই (`if phone:` ব্রাঞ্চ)।

### ১.৩ `fazle_employees_legacy.full_name` 🔴

`modules/escort_lifecycle/__init__.py:510`

```sql
SELECT e.employee_id, e.full_name FROM fazle_employees_legacy e WHERE e.full_name ILIKE $1
```

`fazle_employees_legacy`-তে নামের কলাম **`employee_name`**; `full_name` আছে `fazle_employees`-এ।

### ১.৪ `fazle_knowledge_base` — `value`, `subcategory`, `language` তিনটিই অনির্ধারিত 🔴

টেবিলের সংজ্ঞা (`db/new_tables.sql`, `003`, `029`, `021`):
`id, category, key, trigger_keywords, reply_text, reply_short, tags, confidence, is_active, created_at, updated_at`

কিন্তু ব্যবহার:

| ফাইল | কলাম |
|---|---|
| `modules/kb_upload/routes.py:108` | INSERT → `subcategory`, `value`, `language` |
| `modules/kb_upload/routes.py:181,195,209` | SELECT → `subcategory`, `value` |
| `modules/business_read_service.py:223` | হোয়াইটলিস্ট → `subcategory` |
| `modules/ai_readonly_tools/__init__.py:593,601,605` | `ai_read_kb_articles.subcategory` |
| `scripts/sync_knowledge_base_to_runtime.py:144` | INSERT → `value`, `subcategory` |
| `scripts/seed_recruitment_kb.sql:10` | INSERT → `value`, `language` |
| `db/migrations/012_ai_readonly_views.sql:156` | `k.subcategory` (VIEW-এর ভেতর!) |
| `db/migrations/021_sprint3a_...sql` (৯ বার) | INSERT → `value` |

**গুরুতর প্রভাব:** `012`-এর `ai_read_kb_articles` ভিউ `k.subcategory` সিলেক্ট করে — পরিষ্কার
(clean) ডেটাবেজে এই মাইগ্রেশন **FAIL** করবে। `003`-এর মন্তব্য (`-- DB had: key, value, tags`)
প্রমাণ করে `value` লাইভ ডিবিতে আছে, কিন্তু রিপোর কোনো `CREATE TABLE`-এ নেই।

### ১.৫ `fazle_payment_drafts.method` 🔴

`modules/fazle_payment_ingest/__init__.py:350` — INSERT-এ `method`; টেবিলে আছে **`payment_method`**।

### ১.৬ `fpe_sync_checkpoints.last_checked_at` 🔴

`modules/fazle_payroll_engine/checkpoint.py:22` (SELECT), `:36` (UPDATE SET),
`modules/fazle_payroll_engine/routes.py:1703` (SELECT)।
টেবিলে আছে **`last_sync_at`** (`001_fpe_schema.sql:161`)। `last_checked_at` আছে শুধু `social_backlog_state`-এ।

### ১.৭ `fpe_gap_scan_runs.skipped_no_content` 🔴

`modules/fazle_payroll_engine/gap_scan.py:198` — INSERT-এ `skipped_no_content`;
`004_fpe_zero_loss.sql:79-91`-এর সংজ্ঞায় এই কলাম নেই।

---

# 🟠 শ্রেণি ২ — প্রোডাকশন কোডে ব্যবহৃত টেবিল, যার `CREATE TABLE` রিপোতেই নেই

| টেবিল | প্রোডাকশন কোডে রেফারেন্স | একমাত্র সংজ্ঞা |
|---|---|---|
| `wbom_candidates` | **৪৯** বার (`app/main.py`, `modules/conversation_state.py`, `modules/hermes_dispatch.py`, `modules/fazle_bridge_poller`) | শুধু `tests/conftest.py:170` |
| `wbom_candidate_conversations` | `modules/recruitment_flow/__init__.py` (INSERT সহ) | শুধু `tests/conftest.py:196` |
| `fazle_knowledge_governance` | `modules/conversation_layer/__init__.py:134` (`category, fact_key, fact_value, status, deprecated_at`) | কোথাও নেই |
| `escort_evidence_event` | `modules/business_read_service.py:88` (১০টি কলাম) | কোথাও নেই |

`tools/prefix_objects.json` (লাইভ ডাম্প) নিশ্চিত করে — এই টেবিলগুলো প্রোডাকশনে আছে।
মানে: **রিপো থেকে ক্লিন ইনস্টল করলে এই কোডপথগুলো সব ক্র্যাশ করবে।**
`029`-এর ২৭-টেবিল বুটস্ট্র্যাপ এই দুটিকে (`wbom_candidates*`) মিস করেছে।

---

# 🟡 শ্রেণি ৩ — `tests/conftest.py` বনাম মাইগ্রেশন (কলাম-হেডার অমিল)

`db/MIGRATION_INVENTORY.md`-ই স্বীকার করে: *"conftest.py's guessed schema is already known to disagree with production"*। নিচে প্রমাণসহ তালিকা (২২ টেবিল)।

সবচেয়ে বিপজ্জনকগুলো — যেখানে **টেস্ট পাস করে কিন্তু প্রোডাকশন ব্রেক করে**:

| টেবিল | conftest (ভুয়া) | মাইগ্রেশন/প্রোডাকশন (সত্যি) |
|---|---|---|
| `wbom_salary_records` | `record_id`, `salary_month`, `amount`, `status` | `salary_id`, `month`+`year`, `net_salary`, `payment_status` (+৮টি) |
| `llm_conversation_log` | `created_at` | `ts`, `user_id`, `usage_data`, `trainable` |
| `fazle_report_cache` | `payload` | `payload_json`, `report_name`, `created_at` |
| `fazle_service_heartbeats` | `service_name` | `service`, `meta_json` |
| `fazle_roles` | `id` (PK) | PK নেই — `name`, `level`, `description` |
| `fazle_error_log` | `id` নেই | `id` আছে |
| `fazle_admin_roles` | `id` | `granted_at` |
| `fazle_whatsapp_messages` | `created_at` | `received_at` (+২১টি কলাম অনুপস্থিত) |
| `wbom_escort_programs` | `importer`, `cargo_type`, `created_at` | `mother_vessel`, `lighter_vessel`, `master_mobile`, `total_days`, `replaces_program_id` |

বাকি অমিল: `fazle_contacts` (১১), `wbom_cases` (১৭), `fazle_outbound_queue` (৮),
`wbom_attendance` (৫), `fazle_cash_transactions_archive` (৩), `fazle_runtime_settings` (৪),
`wbom_employee_requests` (৫), `wbom_payroll_runs` (২), `wbom_payroll_approval_log` (১),
`wbom_payroll_run_items` (১), `escort_roster_entries` (১), `assistant_feature_flags` (১)।

---

# 🟣 শ্রেণি ৪ — টেবিল-নেমিং ও মাইগ্রেশন-সিস্টেম অমিল

### ৪.১ চারটি সমান্তরাল মাইগ্রেশন সিস্টেম

| পাথ | ফাইল | রানার | স্ট্যাটাস |
|---|---:|---|---|
| `db/migrations/` | ৯৫ | `db/migrate.py` | ✅ ক্যানোনিক্যাল |
| `modules/fazle_payroll_engine/migrations/` | ১৪ | **প্রতি স্টার্টআপে** `start_fpe()` | 🗄️ legacy |
| `migrations/` (রুট) | ৬ | কোনোটিই নয় (ম্যানুয়াল `psql -f`) | 🗄️ legacy |
| ইনলাইন Python DDL | ৪ মডিউল | প্রতি স্টার্টআপে | 🗄️ legacy |

### ৪.২ `001_fpe_schema.sql`-এ একই ফাইলে দুই প্রিফিক্স

ফাইলের হেডারে লেখা: *"All tables use `fpe_*` prefix"* — কিন্তু বাস্তবে:

```
fpe_wa_messages, fpe_message_processing_state, fpe_parser_results,
fazle_employees,            ← fazle_
fpe_employee_aliases,
fazle_cash_transactions,    ← fazle_
fazle_employee_ledger,      ← fazle_
fpe_unmatched_messages, fpe_accounting_audit_logs, fpe_sync_checkpoints
```

### ৪.৩ মাইগ্রেশন ০৯০–০৯৬: `fpe_*` টেবিল রিপোতেই নেই, তবুও রিনেম করা হচ্ছে

`094/095/096` চালায়:
```sql
ALTER TABLE IF EXISTS fpe_cash_transactions RENAME TO fazle_cash_transactions;
ALTER TABLE IF EXISTS fpe_employee_ledger  RENAME TO fazle_employee_ledger;
ALTER TABLE IF EXISTS fpe_employees        RENAME TO fazle_employees;
```
কিন্তু `001_fpe_schema.sql` **ইতিমধ্যেই** `fazle_*` নামেই টেবিল তিনটি তৈরি করে।
আর `db/migrations/029` ইতিমধ্যেই `fazle_contacts`, `fazle_whatsapp_messages`,
`fazle_employees_legacy`, `fazle_cash_transactions_archive` তৈরি করে।
→ ফ্রেশ বিল্ডে `090`–`093` সম্পূর্ণ **নো-অপ**।

### ৪.৪ স্টার্টআপ-অর্ডারিং হ্যাজার্ড (সবচেয়ে বিপজ্জনক) 🔴

`modules/fazle_payroll_engine/__init__.py:29-30` — `start_fpe()` **প্রতি স্টার্টআপে**
`modules/fazle_payroll_engine/migrations/*.sql` চালায়। অর্থাৎ:

1. প্রি-ইউনিফিকেশন ডিবিতে `fazle_employees` নেই (আছে `fpe_employees`)।
2. অ্যাপ স্টার্ট → `CREATE TABLE IF NOT EXISTS fazle_employees` → **ফাঁকা টেবিল তৈরি**।
3. এরপর `db/migrate.py` চালু হলে `096`:
   `ALTER TABLE IF EXISTS fpe_employees RENAME TO fazle_employees;`
   → `IF EXISTS` শুধু **সোর্স** চেক করে, **টার্গেট** নয় → `42P07: relation "fazle_employees" already exists` → মাইগ্রেশন ব্যর্থ।

একই ঝুঁকি `fazle_cash_transactions` (094) ও `fazle_employee_ledger` (095)-এর জন্য।

---

# ⚪ শ্রেণি ৫ — একই ধারণা, অনেক নাম (কনভেনশন ড্রিফট)

### ৫.১ `fazle_cash_transactions` বনাম `fazle_cash_transactions_archive` — হেডার-টু-হেডার

একই ধারণা (ক্যাশ লেনদেন), কিন্তু কলাম-হেডার একেবারে আলাদা:

| ধারণা | `fazle_cash_transactions` (ক্যানোনিক্যাল) | `fazle_cash_transactions_archive` (legacy) |
|---|---|---|
| প্রাইমারি কি | `id` | `transaction_id` |
| লেনদেন শনাক্তকারী | `txn_ref` | `reference_number` |
| তারিখ | `txn_date` | `transaction_date` + `transaction_time` |
| পেমেন্ট মাধ্যম | `payout_method` | `payment_method` |
| পেমেন্ট ফোন | `payout_phone` | `payment_mobile` / `payment_number` |
| ধরন | `txn_category` | `transaction_type` |
| রিভার্সাল ফ্ল্যাগ | `is_reversal` | `is_reversed` |
| রিভার্সাল রেফ | `reversed_txn_id` | `reversal_of` |
| **`employee_id` অর্থ** | → `fazle_employees.id` | → `fazle_employees_legacy.employee_id` |

**একই `employee_id` নাম, দুইটি সম্পূর্ণ ভিন্ন কি-স্পেস** — এটি পুরো কোডবেজের বড় ফাঁদ।
মাইগ্রেশন `020`-এর মন্তব্যই বলে: *"`fazle_cash_transactions.employee_id` FKs to `fazle_employees(id)`, not this"*।

### ৫.২ অন্যান্য

- **ফোন**: ১,৬২৫ কলামের মধ্যে **৪২টি ভিন্ন নামে** ফোন নাম্বার (`phone`, `sender_number`, `employee_mobile`, `primary_phone`, `payout_phone`, `payout_mobile`, `master_mobile`, `escort_mobile`, `whatsapp_number`, `canonical_phone`, `phone_last10`, `resolved_phone`, …)
- **নাম**: `employee_name` / `full_name` / `escort_name` / `display_name` / `employee_name_raw` / `sender_name`
- **`created_at`**: `created_at` / `received_at` / `ts` / `started_at` / `recorded_at` / `enqueued_at` / `requested_at` / `submitted_at`

---

## সুপারিশ (প্রাধান্য অনুযায়ী)

1. **১.১–১.৭ নম্বর বাগগুলো ঠিক করুন** — এগুলো রানটাইম-ব্রেকিং; বিশেষ করে ১.২ (কোয়েরিতে ফোন
   নাম্বার থাকলেই ক্র্যাশ) ও ১.৬ (প্রতি সিঙ্ক পাসে কল হয়)।
2. **`fazle_knowledge_base`-এ `value`/`subcategory`/`language` যোগ করুন** অথবা কোড+মাইগ্রেশন `012`/`021` থেকে সরিয়ে দিন — বর্তমানে উভয় দিকই ভাঙা।
3. **`wbom_candidates` / `wbom_candidate_conversations` / `fazle_knowledge_governance` / `escort_evidence_event`**-এর `CREATE TABLE` যোগ করুন (`db/migrations/`)।
4. **`conftest.py` পুনর্লিখন করুন** মাইগ্রেশন থেকে, হাতে-আন্দাজ না — `029` ইতিমধ্যেই pg_dump-ভিত্তিক, সেটিকেই সোর্স ধরুন।
5. **০৯৪–০৯৬ রিনেম আগে চালান, তারপর অ্যাপ স্টার্ট** — অথবা `001_fpe_schema.sql`-কে আগের `fpe_*` নামে ফিরিয়ে দিন, যাতে স্টার্টআপে ফাঁকা টেবিল না তৈরি হয়।
6. **একটি নেমিং-কনভেনশন ডকুমেন্ট** তৈরি করুন (`PHONE_NORMALIZER_CONVENTION.md`-এর মতো) — কবে `phone` আর কবে `mobile`, `created_at` নাকি `received_at`।

---

## পুনরুৎপাদনযোগ্যতা

```bash
# স্কিমা বিল্ড (all 4 migration dirs, 2-pass)
python3 /home/user/_naming_audit/build_all.py
# INSERT/UPDATE কলাম চেক
python3 /home/user/_naming_audit/scan2.py
# alias-qualified (t.col) চেক
python3 /home/user/_naming_audit/scan5.py
# conftest বনাম migration
python3 /home/user/_naming_audit/diff_schema.py
# ডকস
python3 /home/user/_naming_audit/scan_docs.py
```
