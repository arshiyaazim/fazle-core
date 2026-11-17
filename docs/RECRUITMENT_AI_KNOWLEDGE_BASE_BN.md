# নিয়োগ-সংক্রান্ত AI জ্ঞানপত্র: WhatsApp প্রার্থী কথোপকথন

> **নথির ধরন:** বট নির্মাতা/প্রম্পট ও FAQ লেখকদের জন্য বিস্তৃত বাস্তবায়ন-সহায়ক নথি। এটি নতুন বা স্বতন্ত্র কোম্পানি-নীতি নয়; বিদ্যমান ক্যানোনিকাল নীতি ও অনুমোদন রেজিস্টারের পাঠযোগ্য সংকলন। কোনো দ্বন্দ্ব হলে `knowledge_base/00_governance/recruitment_fact_authority.json` এবং ক্যানোনিকাল নিয়োগ নীতিই প্রাধান্য পাবে।
>
> **নীতি যাচাই:** ক্যানোনিকাল Recruitment Policy ও Workflow-এর `last_verified` তারিখ 2026-09-26। বট চালুর আগে রেজিস্টারের বর্তমান সংস্করণ ও অফিস-অনুমোদিত যোগাযোগ যাচাই করতে হবে।

## ১. উদ্দেশ্য ও সীমা

এই নথি WhatsApp-ভিত্তিক নিয়োগ সহকারীর জন্য একটি বিস্তৃত আলাপ-নির্দেশিকা: প্রার্থীর প্রশ্ন বুঝে সঠিক অনুমোদিত তথ্য দেওয়া, আবেদন সংগ্রহে সহায়তা করা, প্রয়োজনীয় পরবর্তী প্রশ্ন করা, এবং অনিশ্চিত বা সংবেদনশীল বিষয়ে নিরাপদে অফিসে পাঠানো।

**কোনো নথি বা FAQ সব সম্ভাব্য প্রশ্নের নির্দিষ্ট উত্তর নিশ্চিত করতে পারে না।** অজানা, নতুন, ব্যক্তিগত, আইনগত, বর্তমান-সময়-নির্ভর বা রেজিস্টারে অনির্ধারিত প্রশ্নে তথ্য বানিয়ে উত্তর না দিয়ে পরিষ্কারভাবে অনিশ্চয়তা জানানোই সঠিক উত্তর। লক্ষ্য হলো সব প্রশ্নের ধরন সামলানো—প্রতিটি প্রশ্নে কৃত্রিমভাবে নিশ্চিত তথ্য দেওয়া নয়।

এই বট:

- প্রার্থীর সাধারণ নিয়োগ-প্রশ্নে বাংলায়, ইংরেজিতে বা Banglish-এ উত্তর দিতে পারে।
- সাধারণ নিয়োগ-তথ্য ও আবেদন-তথ্য সংগ্রহে সহায়তা করতে পারে।
- **নিজে নিয়োগদাতা, যাচাইকারী বা নির্বাচনকারী নয়।**
- নির্বাচন, বেতন-চুক্তি, শূন্যপদ, সাক্ষাৎকারের সময়, যোগদানের তারিখ, ডিউটি বা সুবিধার নিশ্চয়তা দিতে পারে না।
- কর্মীর ব্যক্তিগত বেতন/পেমেন্ট, ক্লায়েন্ট, জাহাজ/কার্গো, অভ্যন্তরীণ অপারেশন বা অন্য ব্যক্তির তথ্য প্রকাশ করতে পারে না।

## ২. তথ্যের কর্তৃত্ব ও অগ্রাধিকার

নিয়োগ-উত্তর তৈরির সময় উৎসের অগ্রাধিকার:

1. `knowledge_base/00_governance/recruitment_fact_authority.json`-এ `current_approved` fact।
2. `knowledge_base/01_employee_knowledge/recruitment_policy.md`-এর ক্যানোনিকাল প্রার্থী-নীতি।
3. `knowledge_base/05_workflows/recruitment_workflow.md`-এর কথোপকথন ও lifecycle নিয়ম।
4. নিচের কোড/স্কিমা তথ্য কেবল বট-আচরণ বোঝাতে; ব্যবসায়িক নীতি বা প্রার্থীর প্রতিশ্রুতি হিসেবে নয়।
5. পুরোনো FAQ, seed SQL, generated KB, archive, historical report, chat history, candidate claim, LLM/RAG output—কандидат-facing policy-г өөрчлөх эрхгүй.

### Fact статустай ажиллах дүрэм

- **Current approved:** заасан нөхцөлтэй нь хамт хэрэглэж болно.
- **Unverified:** баталгаатай утга хэлж болохгүй; оффист шалгуулахыг санал болго.
- **Conflicting:** өрсөлдөж буй тоонуудын аль нэгийг сонгон баттай хэлж болохгүй.
- **Historical / superseded:** одоогийн бодлого гэж бүү хэл.
- **Кодод ажиллаж байна:** энэ нь компанийн бодлого батлагдсан гэсэн үг биш. Кодын утга ба хүний нөөцийн бодлогыг ялга.

Мэдээлэл дутуу/зөрчилтэй үед үндсэн хариу:

> “Энэ мэдээллийн одоогийн баталгаатай нөхцөл бүртгэлд алга байна। অনুগ্রহ করে অফিসে যাচাই করুন।”

প্রশ্নটি বাংলায় হলে:

> “এই তথ্যের বর্তমান নিশ্চিত মান আমাদের কাছে নেই। অনুগ্রহ করে অফিসে যোগাযোগ করে যাচাই করুন।”

## ৩. অনুমোদিত প্রার্থী-তথ্য: দ্রুত তথ্যভান্ডার

### ৩.১ পরিচয়, ঠিকানা ও যোগাযোগ

- **অনুমোদিত Recruitment brand:** AL-RIFA'I INTEGRATED SERVICES.
- Al-Aqsa আগের পরিচ��ত নাম হিসেবে কথোপকথনের প্রেক্ষাপটে থাকতে পারে; তার সঙ্গে বর্তমান প্রতিষ্ঠানের আইনগত সম্পর্ক যাচাই করা হয়েছে—এমন দাবি করা যাবে না।
- **Recruitment office:** ভিক্টোরিয়া গেইট # ০১, আগ্রাপাড়া (আগ্রাপারা), Victoria Gate #1, উত্তর কাট্টলি-৪২১৭, একে খান মোড়, থানা: পাহাড়তলি, চট্টগ্রাম।
- **অফিস সময়:** সকাল ০৯:০০–বিকেল ০৫:০০।
- **শুক্রবার:** বন্ধ।
- **প্রকাশ্য Recruitment যোগাযোগ:** 01958-122300.
- ক্যানোনিকাল নীতিতে ঠিকানার ইংরেজি/বাংলা বানানের ভিন্নতা থাকতে পারে; ঠিকানার মূল landmark ও চট্টগ্রাম পরিচয় অক্ষুণ্ণ রাখো। পুরোনো সময়/নম্বর দিয়ে বর্তমান তথ্য প্রতিস্থাপন কোরো না।

### ৩.২ স্বীকৃত চাকরির পদ

1. Escort
2. Survey Scout / Survey Escort
3. Security Guard
4. Security Supervisor
5. Assistant Supervisor / Assistant Security Supervisor
6. Operation Officer
7. Security In-Charge
8. Marketing Officer
9. Ghat Supervisor

এটি অনুমোদিত **পদের ধরন**, বর্তমানে খোলা vacancy-র তালিকা নয়। কোনো পদে vacancy আছে কি না, শূন্যসংখ্যা, আবেদন-শেষ তারিখ, নির্দিষ্ট client/site—баталгаажаагүй. Бот “এই পদে এখন লোক নিচ্ছে” гэж зөвхөн тухайн үеийн эрх бүхий баталгаатай эх сурвалж байвал хэлнэ.

### ৩.৩ কাজের প্রকৃতি ও স্থান: সীমিতভাবে বলার নিয়ম

নীতিতে দায়িত্বের পূর্ণাঙ্গ, অনুমোদিত job-description নেই। ক্যানোনিকাল নীতিতে নিচের বর্ণনাগুলো **role-scoped evidence** হিসেবে আছে, নিশ্চিত নিয়োগ-শর্ত নয়:

- Escort / Survey Escort: vessel/cargo assignment, movement/protection, tally/count ও completion-record-সম্পর্কিত কাজ।
- Security Guard: assigned post-এর নিরাপত্তা, রিপোর্টিং ও supervisor নির্দেশনা অনুসরণ।
- Security Supervisor / Assistant Supervisor: দল তদারকি, field coordination ও reporting।
- Operation Officer: নিয়োগ-সমন্বয়, duty distribution, field supervision, client communication, reporting ও office operations।
- Security In-Charge: security team oversight ও incident escalation।
- Ghat Supervisor: ghat/loading-point coordination ও assignment supervision।
- Marketing Officer: প্রার্থী যোগাযোগ, সুযোগ ব্যাখ্যা ও আগ্রহ রেকর্ড করা।

উত্তরে এগুলো ব্যাখ্যা করতে হলে “নথির বর্ণনা অনুযায়ী/সাধারণত সম্পর্কিত কাজ” বলে সীমা বোঝাও; কাজের সুনির্দিষ্ট তালিকা, client, vessel, cargo, duty assignment বা vacancy প্রতিশ্রুতি দিও না।

প্র্যাকটিক্যাল প্রশিক্ষণ/ডিউ��ির সম্ভাব্য উদাহরণ হিসেবে vessel, security post ও Narayanganj ghat উল্লেখ আছে। এতে সব প্রার্থী বা সব role ওই স্থানগুলোতেই কাজ করবেন гэсэн үг биш. Читтагонг, Монгла, Дакка зэрэг хотод role тус бүрийн тогтмол байршил батлагдаагүй; оффист шалгуулах.

## ৪. যোগ্যতা ও আবেদন

### ৪.১ সাধারণ যোগ্যতা

- **বয়স:** ১৮–৫৫ বছর।
- **শারীরিক অবস্থা:** শারীরিকভাবে সক্ষম হতে হবে।
- নতুন এবং অভিজ্ঞ—উভয় প্রার্থীই আবেদন করতে পারেন।
- এই সাধারণ শর্ত পূরণ মানেই selection নয়; office review ও role-fit নির্ধারণ প্রয়োজন।

### ৪.২ শিক্ষাগত যোগ্যতা ও অভিজ্ঞতা

- **Escort / Survey:** অষ্টম শ্রেণি, দাখিল বা আলিম পর্যায়ের শিক্ষার নির্দেশনা আছে। পূর্ব অভিজ্ঞতা বাধ্যতামূলক নয়।
- **Operation Officer:** স্নাতক ডিগ্রি প্রয়োজন।
- **অন্য পদ:** পদভিত্তিক যোগ্যতা সম্পর্কে অনুমোদিত নির্দিষ্ট তথ্য নেই; অনুমান করে উত্তর দিও না।
- কোনো সাধারণ/সকল পদের জন্য লাইসেন্স বা বিশেষ certificate-এর বাধ্যতামূলক তালিকা নেই। যে role-এর জন্য এমন প্রশ্ন আসে, office confirmation চাও।
- “অষ্টম শ্রেণির সার্টিফিকেট বাধ্যতামূলক নয়” ধরনের পুরোনো/reference-only wording-কে ক্যানোনিকাল eligibility-এর ওপর প্রাধান্য দিও না।

### ৪.৩ আবেদন-তথ্য ও WhatsApp intake

বর্তমান structured intake-এর মূল ধাপ:

`নাম → বয়স → এলাকা/বর্তমান ঠিকানা → পছন্দের পদ → অভিজ্ঞতা → ফোন নম্বর নিশ্চিতকরণ`

সিস্টেমে ব্যবহৃত field-গুলোর মধ্যে full name, age, area, job preference, experience years এবং confirmed phone আছে। Policy-তে education-ও প্রাসঙ্গিক intake তথ্য; তবে live structured funnel-এ education আলাদা নির্দিষ্ট ধাপ নয়. Бот шаардлагатай бол боловсролыг тодруулж болох ч “бүртгэлийн заавал байх талбар” гэж хэлж болохгүй.

- প্রার্থী আগে থেকেই নির্ভরযোগ্য ফোন নম্বর দিয়ে থাকলে আবার চাইবে না।
- বর্তমান সেশন/অনুমোদিত history-তে নির্ভরযোগ্যভাবে থাকা তথ্য পুনরায় জিজ্ঞেস করবে না।
- এক বার্তায় একাধিক প্রশ্ন থাকলে আগে অনুমোদিত তথ্যের উত্তর দাও, তারপর পরবর্তী প্রয়োজনীয় intake প্রশ্ন করো।
- অস্পষ্ট তথ্য হলে শুধু প্রয়োজনীয় clarification চাও।
- intake score, WhatsApp display name বা প্রার্থীর নিজের দাবি পরিচয়/শিক্ষা/অভিজ্ঞতা যাচাইয়ের প্রমাণ নয়।

## ৫. প্রয়োজনীয় কাগজপত্র ও ফি

### ৫.১ যোগদানের কাগজপত্র

প্রথম অফিস-ভিজিটে যোগদানের জন্য নিচের **সাতটি** নথি আনতে হবে:

1. NID অথবা জন্মনিবন্ধন।
2. চেয়ারম্যান সার্টিফিকেটের মূল কপি।
3. শিক্ষাগত সনদ।
4. ২ কপি স্ট্যাম্প-সাইজ ছবি।
5. ৪ কপি পাসপোর্ট-সাইজ ছবি।
6. CV.
7. অভিভাবকের NID.

কোনো কাগজ না থাকলে অফিস অতিরিক্ত সময় দিতে পারে; নির্দিষ্ট সময়সীমা বা automatic extension অনুমোদিত নয়। কাগজ গ্রহণ মানে formal verification বা hiring decision নয়। আলাদা আবেদন-পূর্বে সব নথি WhatsApp-এ পাঠাতে হবে—এমন নির্দেশ অনুমোদিত নয়।

### ৫.২ ফি ও অর্থ-সংক্রান্ত নিরাপদ উত্তর

- অনুমোদিত ফর্ম ফি: **৳৩৩০**।
- অনুমোদিত যোগদান/প্রশিক্ষণ ফি: **৳৩,৫০০**।
- আগাম অর্থপ্রদান চাকরিতে যোগদানের absolute prerequisite নয়। আর্থিক অসুবিধা থাকলে আলোচনা করা যেতে পারে।
- অবৈধ ঘুষ অনুমোদিত নয়।
- ৳৫০০ মাসিক বেতন কর্তন ও fee ফেরতের arrangement-এর নীতি-উল্লেখ আছে; সুনির্দিষ্ট কর্তন/ফেরতের calendar অনির্ধারিত। নিজে থেকে installment count, deduction start date, ফেরতের তারিখ বা “ছয় মাস পরে সাত মাসে ফেরত” বলে নিশ্চিত কোরো না।
- পুরোনো joining-rule/reference file-এ minimum advance, নির্দিষ্ট refund timeline বা fee-এর অন্য বর্ণনা থাকতে পারে; সেগুলো current policy register-এ অনুমোদিত নয়।
- কোনো ব্যক্তিগত নম্বরে টাকা পাঠাতে বলো না; payment channel বা receipt process বর্তমান নিয়োগ রেজিস্টারে নিশ্চিত না থাকলে অফিসে যাচাই করতে বলো।

## ৬. বেতন, ডিউটি, প্রশিক্ষণ ও সুবিধা

### ৬.১ অনুমোদিত цалин

| Позиция и үе шат | Батлагдсан дүн |
|---|---:|
| Operation Officer — trial | ৳১২,০০০–৳১৮,০০০ |
| Operation Officer — permanent | ৳১৮,০০০–৳৩৫,০০০+ |
| Security Guard — probation | ৳১০,০০০–৳১৩,০০০ |
| Security Guard — permanent | ৳২৪,৭০০ |
| Escort / Survey — training | ৳১০,০০০–৳১৫,০০০ |

- Escort/Survey training-পরবর্তী salary-র দুটি competing value আছে: ৳১২,০০০–৳২৪,০০০ এবং ৳১২,০০০–৳১৭,০০০। কোনোটি নিশ্চিত করে বলবে না; office verification চাইবে।
- অন্য পদের salary, দৈনিক rate, shift-rate formula বা নির্দিষ্ট duty-day হিসাব অনুমোদিত নয়।
- বেতন দেওয়ার নির্দিষ্ট তারিখ/মাসিক schedule অনুমোদিত নিয়োগ-নীতিতে নেই।
- নিয়োগ-নীতিতে candidate salary-এর নির্দিষ্ট payment method নেই। অন্য payment/employee documentation-এ bKash/Nagad/cash/bank দেখা গেলেও তা candidate-এর guaranteed salary method নয়।
- বেতন থেকে কোনো কাটা/advance/bonus কীভাবে হবে—শুধু register-এ অনুমোদিত হলে বলো।

### ৬.২ প্রশিক্ষণ ও probation

- School training: ১৫ দিন, unpaid.
- প্রার্থীকে day one থেকেই vessel, security post বা Narayanganj ghat-এ practical training/duty-তে পাঠানো হতে পারে। ওই practical workplace-এ পাঠানো হলে salary চলে—কিন্তু নির্দিষ্ট ব্যক্তির posting office-ই নিশ্চিত করবে।
- Initial probation: ৩ মাস; অতিরিক্ত ৩ মাস বাড়ানো যেতে পারে; সর্বোচ্চ মোট ৬ মাস।
- Escort training-র বেতন-পরিমাণ টেবিলে আলাদা অনুমোদিত; school training ১৫ দিনের unpaid নীতির সঙ্গে এক করে ফেলো না। ব্যক্তি কোন training track-এ আছেন, তা অস্পষ্ট হলে জিজ্ঞেস করো/অফিসে যাচাই করো।

### ৬.৩ কাজের সময়, overtime, ছুটি ও অন্যান্য সুবিধা

- Field/Escort duty: অ্যাসাইনমেন্ট অনুযায়ী আনুমানিক ৬–৮ ঘণ্টা।
- Security Guard day shift: ০৮:০০–২০:০০.
- Security Guard night shift: ২০:০০–০৮:০০.
- Overtime লাগতে পারে; overtime rate নিশ্চিত নয়।
- সাপ্তাহিক/মাসিক leave, food, accommodation, bonus, travel allowance এবং role-wise অন্যান্য benefit-এর নিশ্চিত বর্তমান নিয়ম নেই।
- কোনো অনির্ধারিত সুবিধাকে “কোম্পানি দেবে” বা “salary-র মধ্যে আছে” বলে প্রতিশ্রুতি দিও না।

## ৭. সাক্ষাৎকার, নির্বাচন ও joining-এর lifecycle

প্রক্রিয়ার ধারণাগত ক্রম:

`আগ্রহ → আবেদনকারী শনাক্তকরণ → পদ/যোগ্যতা → intake → documents → interview/office review → selection → training/practical learning → probation/readiness → joining → assignment/deployment → active employee`

- অফিসের review ও decision প্রয়োজন।
- chatbot-এর উত্তর, intake completion, score, document receipt বা প্রার্থীর দাবি selection/verification/joining/deployment প্রমাণ করে না।
- interview format, selection timing, joining date, same-day duty ও current vacancy status নিশ্চিত নয়।
- “টিম শীঘ্রই যোগাযোগ করবে” ধরনের completion text থাকলেও contact হবে কখন/কীভাবে—তা নিশ্চিত না হলে প্রতিশ্রুত সময় বা callback claim দিও না।
- কোনো ব্যবহারকারী বলেন “আমাকে নিয়োগ দেওয়া হয়েছে” বা “আমার interview ঠিক হয়েছে”—তাঁর বক্তব্যকে কোম্পানির নিশ্চিত record হিসেবে দেখিও না; প্রয়োজন হলে authorized office/admin verification-এ পাঠাও।

## ৮. বটের কথোপকথন-নীতি

### ৮.১ প্রশ্ন শ্রেণিবিন্যাস

আগে intent বুঝে উপযুক্ত একটি বা একাধিক বিষয় বেছে নাও:

- role list / vacancy
- duty / job location / shift
- age / education / experience / health
- application / progress / interview / selection / joining
- documents
- salary / allowances / payment date / method
- fee / advance / deduction / refund
- office address / hours / contact
- training / probation / leave / food / accommodation / overtime
- human/office contact request
- existing employee payroll বা payment question
- client, vessel, cargo, operational/security detail
- অস্পষ্ট/বহুবিষয়ক/নীতি-বহির্ভূত প্রশ্ন

একই বার্তায় একাধিক প্রশ্ন এলে উত্তরযোগ্য অনুমোদিত অংশগুলো আগে উত্তর দাও; এরপর একটিমাত্র প্রয়োজনীয় clarification বা পরবর্তী intake প্রশ্ন করো। পুরোনো topic-এর তথ্য নতুন প্রশ্নে টেনে আনবে না।

### ৮.২ আবেদন শুরুর trigger ও session

- চাকরি/আবেদনের স্পষ্ট আগ্রহ এলে structured intake শুরু হতে পারে।
- bare “job/interested/আগ্রহী” সাধারণ কথায় ভুল trigger হতে পারে বলে code-এ context-sensitive trigger-ও আছে; শুধু একটি সাধারণ শব্দের ভিত্তিতে আবেদন খুলে দেওয়ার বদলে intent নিশ্চিত করো।
- সক্রিয় আবেদন-সেশনের যেকোনো পরবর্তী উত্তরকে আগের ধাপের উত্তর হিসেবে বিবেচনা করতে হতে পারে; keyword না থাকলেই সেটি সাধারণ আলাপ নয়।
- ২৪ ঘণ্টা নিষ্ক্রিয়তার পর session expire হতে পারে। এটি application rejection বা data deletion гэсэн үг биш; session-ын одоогийн төлөвийг шалга.
- session state, message retry, repeated input, বাংলা/ইংরেজি সংখ্যা зэрэг edge case-ийг хэрэгжүүлэлтээр удирдана; кандидатаас шаардлагагүй дахин мэдээлэл бүү нэх.

### ৮.৩ Scoring: зөвхөн implementation note

Live code дахь score нь дараах байдлаар тооцогддог:

- ৬+ жилийн experience: ৬০; ৩–৫: ৪০; ১–২: ২০; ০: ০.
- job preference `Escort / Survey Scout` эсвэл `Security Guard` байвал ২০.
- full name, age, area, job preference бүх талбар байвал ২০.
- cap ১০০; bucket: hot ≥৭০, warm ≥৪০, cold <৪০.

Энэ бол кодын lead-prioritization implementation. Үүнийг албан ёсны selection criterion, candidate-д амласан advantage, cutoff эсвэл hiring guarantee гэж хэлж болохгүй. Эх сурвалжуудын хуучин score тайлбар хоорондоо зөрдөг; ботууд үүнийг зөвхөн дотоод тайлбар гэж үзнэ.

### ৮.৪ Privacy ও sensitive info

- WhatsApp display name-কে verified legal name ধরে নিও না।
- NID/CV-তে থাকা তথ্য কেবল অনুমোদিত access ও প্রয়োজনীয়তার মধ্যে ব্যবহার করো; অস্পষ্ট তথ্য confirm করো।
- অন্য কর্মীর salary, employee ID, bank/bKash number, attendance, leave, payroll বা ব্যক্তিগত record দিও না।
- client identity, vessel contact, cargo detail, shipment/payment formula, security operation বা internal escalation info প্রার্থীকে প্রকাশ কোরো না।
- পরিচয় বা অধিকার যথেষ্ট নিশ্চিত না হলে sensitive প্রশ্নে উত্তর না দিয়ে মানব/অফিস যাচাইয়ে পাঠাও।
- AI output বা কথোপকথনের history কখনো policy source নয়।

### ৮.৫ Human handoff

যখন অফিস বা responsible person-এর সিদ্ধান্ত দরকার:

1. কোন বিষয়ে সাহায্য দরকার ও তা জরুরি কি না সংক্ষেপে বোঝো।
2. অনুমোদিত হলে শুধু প্রকাশ্য Recruitment contact/address দাও।
3. অফিসে যাচাই করতে বলো; callback, owner availability, message delivery, interview slot বা resolution time নিশ্চিত করে বলো না।
4. বর্তমান খোলা vacancy, salary conflict, deduction/refund, overtime, leave/benefit বা ব্যক্তিগত আবেদন-অবস্থা—অফিস review-এর কাছে পাঠাও।

## ৯. প্রস্তুত FAQ উত্তর-নমুনা

নিচের বাক্যগুলো উত্তর তৈরির template; ব্যবহারকারীর নির্দিষ্ট প্রশ্ন অনুযায়ী স্বাভাবিকভাবে বলবে। একই উত্তরে প্রয়োজন নেই এমন তথ্য যোগ করবে না।

**প্রশ্ন: কী কী পদে আবেদন করা যায়?**  
উত্তর: “নিয়োগে স্বীকৃত পদগুলো হলো Escort, Survey Scout/Survey Escort, Security Guard, Security Supervisor, Assistant Supervisor, Operation Officer, Security In-Charge, Marketing Officer এবং Ghat Supervisor। কোন পদে বর্তমানে vacancy আছে তা অফিসে যাচাই করতে হবে।”

**প্রশ্ন: এখন কোন পদে লোক নিচ্ছেন?**  
উত্তর: “বর্তমান vacancy-র নিশ্চিত তালিকা আমার কাছে নেই। অনুগ্রহ করে Recruitment office-এ 01958-122300 নম্বরে যোগাযোগ করে জেনে নিন।”

**প্রশ্ন: বয়স কত হতে হবে?**  
উত্তর: “সাধারণ বয়সসীমা ১৮–৫৫ বছর; শারীরিকভাবে সক্ষম হতে হবে। চূড়ান্ত role-fit অফিস পর্যালোচনা করবে।”

**প্রশ্ন: পড়াশোনা কত দরকার?**  
উত্তর: “Escort/Survey পদের জন্য অষ্টম শ্রেণি, দাখিল বা আলিম পর্যায়ের শিক্ষার নির্দেশনা আছে; Operation Officer-এর জন্য স্নাতক ডিগ্রি প্রয়োজন। অন্য পদের শর্ত অফিসে যাচাই করুন।”

**প্রশ্ন: অভিজ্ঞতা না থাকলে আবেদন করা যাবে?**  
উত্তর: “হ্যাঁ। নতুন ও অভিজ্ঞ—দুই ধরনের প্রার্থী আবেদন করতে পারেন; Escort/Survey পদের জন্য পূর্ব অভিজ্ঞতা বাধ্যতামূলক নয়। নির্বাচন নিশ্চিত নয় এবং role-fit অফিস পর্যালোচনা করবে।”

**প্রশ্ন: কী কাগজ লাগবে?**  
উত্তর: “যোগদানের প্রথম অফিস-ভিজিটে NID বা জন্মনিবন্ধন, মূল চেয়ারম্যান সার্টিফিকেট, শিক্ষাগত সনদ, ২টি স্ট্যাম্প-সাইজ ও ৪টি পাসপোর্ট-সাইজ ছবি, CV এবং অভিভাবকের NID আনুন।”

**প্রশ্ন: বেতন কত?**  
উত্তর: “অনুমোদিত তথ্য অনুযায়ী Operation Officer-এর trial বেতন ৳১২,০০০–৳১৮,০০০ এবং permanent ৳১৮,০০০–৳৩৫,০০০+; Security Guard-এর probation ৳১০,০০০–৳১৩,০০০ এবং permanent ৳২৪,৭০০; Escort/Survey training ৳১০,০০০–৳১৫,০০০। অন্য role বা Escort/Survey training-পরবর্তী অঙ্ক অফিসে যাচাই করতে হবে।”

**প্রশ্ন: Escort/Survey training শেষে salary কত?**  
উত্তর: “প্রশিক্ষণ-পরবর্তী বেতন সম্পর্কে নথিতে ভিন্ন অঙ্ক আছে, তাই নিশ্চিত সংখ্যা দিতে পারছি না। Recruitment office-এ যাচাই করুন।”

**প্রশ্ন: বেতন কবে, কীভাবে পাব?**  
উত্তর: “নির্দিষ্ট বেতন-তারিখ ও প্রার্থী-পর্যায়ের payment method আমার কাছে নিশ্চিত নেই। অফিসে যাচাই করুন।”

**প্রশ্ন: খাবার/থাকা/যাতায়াত/বোনাস আছে?**  
উত্তর: “এই সুবিধাগুলোর role-wise বর্তমান নিয়ম নিশ্চিত নয়। আপনার পদের জন্য Recruitment office-এ যাচাই করুন।”

**প্রশ্ন: ডিউটি কত ঘণ্টা?**  
উত্তর: “Field/Escort duty অ্যাসাইনমেন্ট অনুযায়ী আনুমানিক ৬–৮ ঘণ্টা। Security Guard-এর day shift ০৮:০০–২০:০০ এবং night shift ২০:০০–০৮:০০। অন্য পদের সময় office assignment অনুযায়ী নিশ্চিত করতে হবে।”

**প্রশ্ন: overtime/ছুটি কীভাবে?**  
উত্তর: “Overtime প্রয়োজন হতে পারে, তবে rate এবং leave rules নিশ্চিতভাবে নথিভুক্ত নেই। অফিসে যাচাই করুন।”

**প্রশ্ন: training paid?**  
উত্তর: “School training ১৫ দিন এবং unpaid। তবে day one-এ practical workplace-এ duty/training-এ পাঠানো হলে salary চলে। আপনার ক্ষেত্রে কোন training track প্রযোজ্য তা অফিস নিশ্চিত করবে।”

**প্রশ্ন: probation কতদিন?**  
উত্তর: “প্রাথমিক probation ৩ মাস; আরও ৩ মাস বাড়ানো যেতে পারে, সর্বোচ্চ মোট ৬ মাস।”

**প্রশ্ন: আগে টাকা দিতে হবে?**  
উত্তর: “আগাম অর্থ দেওয়া চাকরিতে যোগদানের বাধ্যতামূলক শর্ত নয়; আর্থিক অসুবিধা অফিসে আলোচনা করা যায়। অনুমোদিত ফি হলো ফর্ম ফি ৳৩৩০ ও যোগদান/প্রশিক্ষণ ফি ৳৩,৫০০। নির্দিষ্ট কর্তন/ফেরতের সময়সূচি নিশ্চিত নয়।”

**প্রশ্ন: কোথায় এবং কখন অফিসে যাব?**  
উত্তর: “অফিস: ভিক্টোরিয়া গেইট # ০১, আগ্রাপাড়া, উত্তর কাট্টলি-৪২১৭, একে খান মোড়, পাহাড়তলি, চট্টগ্রাম। সময় সকাল ০৯:০০–বিকেল ০৫:০০; শুক্রবার বন্ধ। যাওয়ার আগে 01958-122300 নম্বরে যাচাই করতে পারেন।”

**প্রশ্ন: আমাকে কি চাকরিতে নেওয়া হয়েছে/আগামীকাল duty আছে?**  
উত্তর: “আমি নিয়োগ বা duty assignment নিশ্চিত করতে পারি না। আবেদন/কাগজপত্র office review ও decision-এর পর নিশ্চিত হবে। অনুগ্রহ করে অফিসে যাচাই করুন।”

**প্রশ্ন: আমি কর্মী, আমার salary/advance/payment status কী?**  
উত্তর: “এটি কর্মী-নির্দিষ্ট তথ্য। পরিচয় ও অনুমতি যাচাই ছাড়া আমি ব্যক্তিগত payroll/payment তথ্য দিতে পারি না; অনুগ্রহ করে অনুমোদিত অফিস/accounting channel ব্যবহার করুন।”

## ১০. দ্বন্দ্ব, ভুল উত্তর ও পুরোনো তথ্য এড়ানো

এই পুরোনো/өөр эх сурвалжуудтай зөрчил гарч болох тул автоматаар хуулж болохгүй:

- Өмнөх policy/FAQ-д оффис ১০:০০-д нээгдэнэ гэсэн хувилбар, хуучин утасны дугаарууд гардаг; current approved нь 09:00–17:00, Friday বন্ধ, 01958-122300.
- পুরোনো source/FAQ-তে Al-Manaratayn, Al-Aqsa বা অন্য নাম-ঠিকানা দেখা যেতে পারে। বর্তমান Recruitment brand এবং canonical address উপরের authority register অনুযায়ী; Al-Aqsa-র legal relationship নিশ্চিত নয়।
- বেতন, ফি, বয়স, পদ ও সুবিধা বিষয়ে archived report, seed row বা generated KB-তে পুরোনো/বিরোধী মান থাকতে পারে।
- Ops/employee/payment file-এ bKash, Nagad, Bank, salary calculation বা daily rate-এর উল্লেখ থাকা candidate-কে তা দেওয়ার অনুমতি নয়।
- পুরোনো score table ও dead/prototype `resources/recruitment.py` বর্তমান live recruitment policy/workflow-এর বিকল্প নয়।
- “প্রার্থীকে অফিসে আসার আগে ২টার মধ্যে এলে একই দিনে joining হবে” ধরনের reference-only একই-দিনের দাবি অনুমোদিত নয়।

## ১১. আলাদা AI বট বাস্তবায়নের checklist

1. Authority JSON-কে runtime policy source করো; Markdown/FAQ mirror-কে বিকল্প authority কোরো না।
2. প্রতিটি fact-এর সঙ্গে key, status, source, condition ও effective date ধরে রাখো।
3. `unverified/conflicting/historical/superseded` হলে exact সংখ্যা বা promise generate বন্ধ করো।
4. Answer-first করো: ব্যবহারকারীর প্রশ্নের অনুমোদিত অংশের উত্তর দিয়ে তারপর intake চালাও।
5. Session/identity context ব্যবহারে privacy এবং permission gate রাখো।
6. Input validation, বাংলা/ইংরেজি সংখ্যা, duplicate/retry এবং field-lock আচরণের জন্য regression test লিখো।
7. “scored” বা “complete” status-কে hired/selected হিসেবে render কোরো না।
8. WhatsApp auto-send-এর আগে reply policy ও sensitive-content validation করো; unresolved fact-এর জন্য human handoff দাও।
9. Current vacancy, schedule, contact বা salary পরিবর্তন হলে authorization register-এর approval process-এ update করো; শুধু prompt/seed FAQ বদলে policy পরিবর্তন কোরো না।
10. বটের fallback, contact transfer, message delivery ও callback-সংক্রান্ত claim পরীক্ষা করো; নিশ্চিত না হলে promise কোরো না।

## ১২. Repository references

এই нэхэмжлэлийн суурь бол дараах repository файлууд; жагсаалт нь өөрөө бүх эх сурвалжийг бүрэн шалгасны баталгаа биш:

- `knowledge_base/00_governance/recruitment_fact_authority.json` — fact бүрийн approval status.
- `knowledge_base/01_employee_knowledge/recruitment_policy.md` — к্যানোনিকাল Recruitment Policy.
- `knowledge_base/05_workflows/recruitment_workflow.md` — к্যানোনিকাল কথোপকথন ба lifecycle.
- `modules/recruitment_flow/__init__.py` — intake trigger, session handling, validation ও score implementation.
- `modules/recruitment_authority.py` — প্রশ্নের সঙ্গে authority fact মেলানো.
- `modules/conversation_layer/prompting.py` — approved বনাম unresolved fact prompt-এ পাঠানো.
- `docs/BRIDGE3_RECRUITMENT_GOLDEN_BASELINE.md` — নির্দিষ্ট তারিখে live code/lifecycle audit; সময়-সীমাবদ্ধ diagnostic evidence, স্বতন্ত্র নিয়োগনীতি নয়.

**শেষ নির্দেশ:** নতুন বা অপ্রত্যাশিত প্রশ্নের উত্তর authority register-এ না থাকলে, সেটি সুন্দর করে অনুমান নয়—সৎভাবে “নিশ্চিত নয়” বলে অফিস যাচাইয়ের পথ দেখানোই সঠিক FAQ উত্তর।
