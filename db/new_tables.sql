-- Fazle Core — New Tables Migration
-- Run once against the postgres database.
-- Safe to re-run (IF NOT EXISTS guards).

-- ── Knowledge Base ─────────────────────────────────────────────────────────────
-- Stores auto-reply templates, FAQ answers, business rules
-- `subcategory`, `value` and `language` are live production columns that this
-- bootstrap never declared — see db/migrations/097_knowledge_base_missing_columns.sql.
-- Added here so a bootstrapped database matches what migrations 012 and 021
-- and the KB upload/seed scripts expect.
CREATE TABLE IF NOT EXISTS fazle_knowledge_base (
    id              SERIAL PRIMARY KEY,
    category        TEXT        NOT NULL,          -- recruitment, escort, payment, faq, complaint
    subcategory     TEXT,                          -- scope within a category
    key             TEXT        NOT NULL UNIQUE,   -- slug e.g. job_details, salary_info
    value           TEXT,                          -- legacy; superseded by reply_text
    language        TEXT,                          -- 'bn' | 'bn-en'
    trigger_keywords TEXT[]     DEFAULT '{}',      -- keywords that trigger this entry
    reply_text      TEXT        NOT NULL,          -- full reply template
    reply_short     TEXT,                          -- condensed version (comments/Facebook)
    tags            TEXT[]      DEFAULT '{}',
    confidence      FLOAT       DEFAULT 1.0,
    is_active       BOOLEAN     DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_category ON fazle_knowledge_base(category);
CREATE INDEX IF NOT EXISTS idx_kb_active   ON fazle_knowledge_base(is_active);

-- ── Recruitment Sessions ───────────────────────────────────────────────────────
-- Tracks step-by-step WhatsApp recruitment conversation state per phone
CREATE TABLE IF NOT EXISTS fazle_recruitment_sessions (
    id               SERIAL PRIMARY KEY,
    phone            TEXT        NOT NULL UNIQUE,
    full_name        TEXT,
    age              INTEGER,
    area             TEXT,
    job_preference   TEXT,
    experience_years INTEGER,
    available_join_date DATE,
    collection_step  TEXT        DEFAULT 'name',   -- current question step
    funnel_stage     TEXT        DEFAULT 'collecting',  -- collecting, scored, assigned, hired, rejected
    score            INTEGER,
    score_bucket     TEXT,                         -- hot, warm, cold
    source           TEXT        DEFAULT 'whatsapp',
    source_bridge    TEXT,                         -- meta, bridge1, bridge2
    source_message   TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recruit_phone ON fazle_recruitment_sessions(phone);
CREATE INDEX IF NOT EXISTS idx_recruit_stage ON fazle_recruitment_sessions(funnel_stage);

-- ── Payment Drafts ─────────────────────────────────────────────────────────────
-- Holds admin-approval-pending payment requests
CREATE TABLE IF NOT EXISTS fazle_payment_drafts (
    id               SERIAL PRIMARY KEY,
    draft_type       TEXT        NOT NULL,  -- escort_payment, advance, salary
    employee_id      INTEGER,
    employee_name    TEXT,
    employee_mobile  TEXT,
    escort_program_id INTEGER,
    duty_days        FLOAT,
    expected_amount  FLOAT,
    approved_amount  FLOAT,
    payment_method   TEXT,                  -- bkash, nagad, cash
    payment_number   TEXT,                  -- bkash/nagad number
    status           TEXT        DEFAULT 'pending',  -- pending, approved, rejected, sent
    admin_phone      TEXT,                  -- which admin to notify
    source_bridge    TEXT,                  -- which bridge to send accountant msg via
    draft_text       TEXT,                  -- formatted text sent to admin
    admin_reply      TEXT,                  -- raw reply from admin
    accountant_msg   TEXT,                  -- formatted message sent to accountant
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pdraft_status   ON fazle_payment_drafts(status);
CREATE INDEX IF NOT EXISTS idx_pdraft_emp      ON fazle_payment_drafts(employee_id);
CREATE INDEX IF NOT EXISTS idx_pdraft_type     ON fazle_payment_drafts(draft_type);

-- ── Add missing columns to existing tables (safe, IF NOT EXISTS) ───────────────
ALTER TABLE fazle_draft_replies
    ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS admin_phone TEXT;

-- ── Knowledge Base Seed Data ───────────────────────────────────────────────────
-- Source: The Fazle System Intent-Based AI txt (resources folder)
-- 11 recruitment auto-reply categories + bonus replies

INSERT INTO fazle_knowledge_base (category, key, trigger_keywords, reply_text, reply_short) VALUES

('recruitment', 'job_details',
 ARRAY['কাজ কি','কাজ কী','details','duty','ডিউটি কত','কঠিন','কত ঘণ্টা','বিস্তারিত','survey scout মানে','জাহাজে কী'],
 E'ধন্যবাদ আমাদের সাথে যোগাযোগ করার জন্য 🙏\n\n👉 পদের নাম: Survey Scout (সার্ভে স্কট)\n\n📌 কাজ কী:\n✔ চট্টগ্রাম বন্দরের লাইটার জাহাজে বিদেশি মালামাল তদারকি\n✔ লোড–আনলোডের সময় হিসাব রাখা\n✔ মালামাল চুরি বা নষ্ট হওয়া প্রতিরোধ\n✔ কাজের প্রয়োজনে জাহাজের সাথে যাত্রা করা\n\n⏰ ডিউটি: গড়ে ৬–৮ ঘণ্টা\n🏠 থাকা: জাহাজেই (থাকা সম্পূর্ণ ফ্রি)\n🍽 খাওয়া: নিজ দায়িত্বে\n\n💰 বেতন:\n🔹 প্রশিক্ষণকাল (৪৫ দিন): ১০,০০০ – ১৫,০০০ টাকা\n🔹 পরে: ১২,০০০ – ১৮,০০০ টাকা\n\n✅ অভিজ্ঞতা লাগবে না — শেখানো হবে\n\n📄 আবেদন করতে পাঠান:\n1. নাম\n2. বয়স\n3. শিক্ষাগত যোগ্যতা\n4. বর্তমান ঠিকানা\n\n📲 WhatsApp: 01958 122322',
 'কাজ: জাহাজে মালামাল তদারকি। বেতন: ১০,০০০–১৮,০০০ টাকা। থাকা ফ্রি। অভিজ্ঞতা লাগবে না।'),

('recruitment', 'job_easy',
 ARRAY['কঠিন কি না','নতুনরা পারবে','নতুন হিসেবে','সহজ কি'],
 E'না ভাই, কাজটা একদম সহজ 😊\n\n📌 মূলত করতে হবে:\n✔ জাহাজে মালামাল দেখাশোনা\n✔ লোড–আনলোড হিসাব রাখা\n✔ চুরি বা নষ্ট হওয়া প্রতিরোধ\n\n✅ নতুনদেরও নেওয়া হয় — ৪৫ দিন ট্রেনিং দেওয়া হয়\n✅ থাকার ব্যবস্থা ফ্রি (জাহাজেই)\n\nআগ্রহী হলে এখনই আপনার নাম, বয়স ও ঠিকানা পাঠান 👇\n📲 WhatsApp: 01958 122322',
 NULL),

('recruitment', 'office_location',
 ARRAY['ঠিকানা','লোকেশন','address','অফিস কোথায়','একে খান','ভিক্টোরিয়া','কোথায় যাব','google map'],
 E'আপনার তথ্য পেয়েছি ✅\n\n👉 সরাসরি অফিসে এসে জয়েন করতে পারবেন\n\n📍 অফিস ঠিকানা:\nআল-আকসা সিকিউরিটি সার্ভিস\nভিক্টোরিয়া গেইট, একে খান মোড়\nপাহাড়তলী, চট্টগ্রাম\n\n🕘 অফিস সময়: সকাল ৯টা – বিকাল ৫টা\n(শুক্রবার ছাড়া সপ্তাহের প্রতিদিন)\n\n📌 আসার সময় সাথে রাখুন:\n✔ NID / জন্ম নিবন্ধন (ফটোকপি)\n✔ পাসপোর্ট সাইজ ছবি (২ কপি)\n\n✔ আসার আগে WhatsApp-এ নিশ্চিত করুন\n📲 WhatsApp: 01958 122322',
 'আল-আকসা সিকিউরিটি সার্ভিস, ভিক্টোরিয়া গেইট, একে খান মোড়, পাহাড়তলী, চট্টগ্রাম। সময়: ৯টা–৫টা।'),

('recruitment', 'want_to_apply',
 ARRAY['করতে চাই','আগ্রহী','interested','apply','আমি রাজি','নেবেন','জয়েন করতে চাই','আমাকে নিবেন'],
 E'ধন্যবাদ আগ্রহ দেখানোর জন্য 🙏\n\nআবেদন করতে নিচের তথ্যগুলো WhatsApp-এ পাঠান:\n\n1️⃣ পূর্ণ নাম\n2️⃣ বয়স\n3️⃣ শিক্ষাগত যোগ্যতা\n4️⃣ বর্তমান ঠিকানা (জেলাসহ)\n5️⃣ মোবাইল নম্বর\n\n📲 WhatsApp: 01958 122322\n\n✅ তথ্য পাওয়ার পর আমাদের টিম দ্রুত যোগাযোগ করবে\n✅ যোগ্য প্রার্থীদের সরাসরি অফিসে ডাকা হবে\n✅ কোনো ভর্তি ফি বা জামানত লাগবে না',
 NULL),

('recruitment', 'negative_comment',
 ARRAY['বাটপার','ভুয়া','fake','শয়তান','ধোঁকাবাজ','প্রতারক','জালেম','fraud'],
 E'আল-আকসা সিকিউরিটি সার্ভিস একটি নিবন্ধিত প্রতিষ্ঠান।\n\n✅ আমরা কখনো কোনো ভর্তি ফি বা জামানত নিই না\n✅ বেতন প্রতি মাসে নিয়মিত প্রদান করা হয়\n✅ আমাদের অফিস সরাসরি যাচাই করা যায়:\n   📍 ভিক্টোরিয়া গেইট, একে খান মোড়, পাহাড়তলী, চট্টগ্রাম\n   📲 WhatsApp: 01958 122322\n\nযদি কেউ আমাদের নামে প্রতারণার শিকার হয়ে থাকেন অথবা কোনো অভিযোগ থাকে — সরাসরি অফিসে আসুন বা WhatsApp করুন। আমরা সমাধান দিতে প্রস্তুত।\n\n🙏 সৎ মানুষদের কাজের সুযোগ দেওয়াই আমাদের লক্ষ্য।',
 'আমরা একটি নিবন্ধিত প্রতিষ্ঠান। কোনো ফি বা জামানত নেওয়া হয় না। সরাসরি অফিসে এসে যাচাই করুন: ভিক্টোরিয়া গেইট, একে খান মোড়, পাহাড়তলী, চট্টগ্রাম। 📲 01958 122322'),

('recruitment', 'requirements_docs',
 ARRAY['কী কী লাগবে','কাগজপত্র','NID','ছবি','বয়সসীমা','অভিজ্ঞতা লাগবে','certificate','সার্টিফিকেট'],
 E'📌 Survey Scout পদে আবেদনের জন্য যা লাগবে:\n\n✔ বয়স: ১৮ – ৪৫ বছর\n✔ শিক্ষা: ন্যূনতম অষ্টম শ্রেণি পাস (SSC হলে ভালো)\n✔ অভিজ্ঞতা: লাগবে না — ৪৫ দিন ট্রেনিং দেওয়া হবে\n✔ শারীরিক সুস্থতা থাকতে হবে\n\n📄 অফিসে আসার সময় সাথে আনুন:\n1. জাতীয় পরিচয়পত্র (NID) / জন্ম নিবন্ধন — ফটোকপি\n2. পাসপোর্ট সাইজ ছবি — ২ কপি\n3. শিক্ষার সার্টিফিকেট (থাকলে)\n\n✅ সার্টিফিকেট না থাকলেও আবেদন করা যাবে\n✅ কোনো ভর্তি ফি নেই, কোনো জামানত নেই\n\n📲 আরো জানতে WhatsApp করুন: 01958 122322',
 NULL),

('recruitment', 'education_concern',
 ARRAY['মাদ্রাসা','সার্টিফিকেট নেই','ক্লাস ৮','দাখিল','আলিম','অষ্টম','পাস করিনি','লিখতে পারি'],
 E'জি ভাই, আবেদন করতে পারবেন 😊\n\n✅ মাদ্রাসার শিক্ষার্থী — চলবে\n✅ দাখিল / আলিম পাস — চলবে\n✅ শুধু পড়তে ও লিখতে পারলেই যথেষ্ট\n✅ সার্টিফিকেট না থাকলেও আবেদন করা যাবে\n\n📌 মূলত দরকার:\n✔ সৎ ও পরিশ্রমী হওয়া\n✔ শারীরিকভাবে সুস্থ থাকা\n✔ জাহাজে থাকতে রাজি থাকা\n\n📄 আবেদন করতে পাঠান:\n1. নাম\n2. বয়স\n3. শিক্ষা (যা আছে সেটাই লিখুন)\n4. ঠিকানা\n\n📲 WhatsApp: 01958 122322',
 NULL),

('recruitment', 'vacancy_status',
 ARRAY['vacancy','আসন আছে','লোক নিচ্ছেন','এখনো নিচ্ছেন','লাস্ট ডেট','পদ খালি','আর কত জন'],
 E'⚠️ সীমিত আসন — এখনো নিয়োগ চলছে\n\n👉 আগ্রহী হলে দেরি না করে এখনই আবেদন করুন\n\n📌 আবেদন করতে WhatsApp-এ পাঠান:\n1. নাম\n2. বয়স\n3. শিক্ষাগত যোগ্যতা\n4. বর্তমান ঠিকানা\n\n📲 WhatsApp: 01958 122322\n\n✔ আগে এলে আগে সুযোগ\n✔ আসন পূর্ণ হয়ে গেলে আর নেওয়া সম্ভব হবে না\n✔ আসার আগে মেসেজ দিয়ে নিশ্চিত করুন',
 NULL),

('recruitment', 'fee_suspicion',
 ARRAY['টাকা লাগবে','ভর্তি ফি','জামানত','joining fee','deposit','registration fee','uniform fee','hidden charge'],
 E'❌ কোনো ভর্তি ফি নেই\n❌ কোনো জামানত নেই\n❌ কোনো ট্রেনিং ফি নেই\n❌ কোনো ইউনিফর্ম ফি নেই\n\n✅ আল-আকসা সিকিউরিটি সার্ভিস কখনো কাউকে টাকা দিতে বলে না\n\n📌 জয়েন করতে শুধু লাগবে:\n✔ NID / জন্ম নিবন্ধন ফটোকপি\n✔ পাসপোর্ট সাইজ ছবি\n\nযদি কেউ আমাদের নামে টাকা চায় — সেটি প্রতারণা। সাথে সাথে আমাদের জানান:\n📲 WhatsApp: 01958 122322\n📍 অফিস: ভিক্টোরিয়া গেইট, একে খান মোড়, পাহাড়তলী, চট্টগ্রাম',
 NULL),

('recruitment', 'salary_complaint',
 ARRAY['বেতন মেরে দিছে','বেতন পাই না','৩ মাসের বেতন','এরা অমানুষ','বেতন দেয় না'],
 E'আমরা আপনার অভিযোগকে গুরুত্বের সাথে নিচ্ছি।\n\nযদি বেতন বা কোনো পাওনা নিয়ে সমস্যা হয়ে থাকে — সরাসরি যোগাযোগ করুন:\n\n📲 WhatsApp: 01958 122322\n📍 অফিস: ভিক্টোরিয়া গেইট, একে খান মোড়, পাহাড়তলী, চট্টগ্রাম\n🕘 সময়: সকাল ৯টা – বিকাল ৫টা\n\n✅ আমরা সব বৈধ পাওনা মিটিয়ে দিতে প্রতিশ্রুতিবদ্ধ\n✅ যেকোনো সমস্যার সমাধান অফিসে এসে নেওয়া যাবে',
 NULL),

('recruitment', 'salary_info',
 ARRAY['বেতন কত','salary কত','টাকা পাব','মাসে কত','income কত','বেতন কাঠামো'],
 E'💰 বেতন কাঠামো:\n\n🔹 প্রশিক্ষণকাল (৪৫ দিন): ১০,০০০ – ১৫,০০০ টাকা\n🔹 পরে: ১২,০০০ – ১৮,০০০ টাকা\n\n✔ কাজের দক্ষতার উপর বেতন বাড়ে\n✔ ভবিষ্যতে অফিসিয়াল পদ ও বেতন বৃদ্ধির সুযোগ',
 NULL),

('recruitment', 'seasonal_hiring',
 ARRAY['সারা বছর নিয়োগ','কেন সারা বছর','এত লোক কেন'],
 E'ভাই, চট্টগ্রাম বন্দরে সারা বছরই জাহাজ আসে।\n\n📌 নিয়োগ চলতে থাকার কারণ:\n✔ জাহাজের সংখ্যা বাড়ছে — তাই লোকের চাহিদা বাড়ছে\n✔ কিছু কর্মী প্রশিক্ষণের পর আরো বড় পদে যায়\n✔ বন্দরের কাজ মৌসুম-ভিত্তিক — নতুন কাজ এলে নতুন লোক লাগে\n\n✅ এটি কোনো প্রতারণার লক্ষণ নয়\n✅ আমরা একটি বৈধ ও নিবন্ধিত প্রতিষ্ঠান\n\nআগ্রহ থাকলে সরাসরি অফিসে এসে যাচাই করুন 🙏',
 NULL),

('escort', 'vessel_order_draft',
 ARRAY['mv','m/v','mother vessel','lighter','escort','এস্কর্ট'],
 E'Mother Vessel: {mother_vessel}\nLighter Vessel: {lighter_vessel}\nMaster''s number: {master_mobile}\nEscort''s name:\nEscort mobile:\nDate: {date} (D/N)',
 NULL),

('payment', 'release_slip_received',
 ARRAY['release slip','রিলিজ স্লিপ','ডিউটি শেষ','কাজ শেষ','মাল খালাস'],
 E'স্লিপ পাওয়া গেছে ✅\nযাচাই করা হচ্ছে। ডিউটি হিসাব প্রস্তুত করা হবে।\nআপনার বিকাশ/নগদ নম্বর জানান।',
 NULL),

('faq', 'greeting_response',
 ARRAY['সালাম','আস্সালামু','hello','hi','হ্যালো','menu','মেনু'],
 E'ওয়ালাইকুম আস্সালাম 🙏\n\nআমি ফজলে — আল-আকসা সিকিউরিটি সার্ভিসের ডিজিটাল সহকারী।\n\nআপনাকে কীভাবে সাহায্য করতে পারি?\n\n1️⃣ চাকরি সম্পর্কে জানতে\n2️⃣ অফিসের ঠিকানা\n3️⃣ বেতন সম্পর্কে\n4️⃣ ডিউটি/পেমেন্ট\n\nযেকোনো প্রশ্ন করুন 👇',
 NULL)

ON CONFLICT (key) DO UPDATE SET
    reply_text = EXCLUDED.reply_text,
    trigger_keywords = EXCLUDED.trigger_keywords,
    updated_at = NOW();
