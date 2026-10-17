# AL-RIFA’I permanent Cash Payment Intent rule

**Owner decision, effective 2026-10-17.** This repository is a source/reference repository for AL-RIFA’I, not an authorization to run a parallel business writer. The current AL-RIFA’I app is the canonical target for the cash workflow. Do not import, post, migrate, deploy, restart, or send messages from this reference repo without explicit Owner authorization.

Until the Owner explicitly revises it, every WhatsApp-derived Cash Transaction must satisfy all of these conditions:

1. Actual sender is the verified `OWNER_PHONE`.
2. Actual recipient and actual direct chat JID resolve to verified `ACCOUNTANT_PHONE`, or an explicitly approved routing rule independently verifies the actual destination. A phone number in message text is not recipient proof.
3. Message text contains cash/payment intent.
4. Employee mobile is reliably extracted; payout mobile is not a substitute for employee identity.
5. Validate amount, payment details, source identity and timestamp as available.
6. Check source-message idempotency and duplicate payment instruction/business key.

Any missing, mismatched or uncertain condition means **no automatic Cash Transaction**; preserve evidence for review. Accountant-originated replies, ordinary chat, unauthorized groups, and other chats cannot create Owner payment instructions. A payment instruction is not proof of receipt/payment completion.

Actual Owner/Accountant contact-book names, phones, internal IDs, `chat_jid`, WhatsApp JID and LID mappings, and bridge/account number must be verified against the private live bridge/contact book and recorded in the private VPS operational handoff and `.env`. Do not guess and do not publish real numbers, JIDs/LIDs, contact exports, or secrets in this public repo. The fixed owner-approved frontend URL and app flow must not change without explicit Owner approval.

Historical SQL migrations are immutable; enforce new behavior in the canonical current application/runtime and new migrations only when genuinely required. This reference repository must not become a second cash writer.