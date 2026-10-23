# 🏢 Harvey Multi-Product & Client Workspaces

Each folder inside `workspaces/` is an **isolated client or product environment**.

```
workspaces/
├── trackkaro/              # TrackKaro AI (3-Second Lead Simulator)
│   ├── harvey.yaml         # Persona, Product, Offer & ICP
│   ├── skills/             # Client-specific product knowledge & battlecards
│   ├── data/               # Isolated SQLite DB (harvey.db), lead states & outbox
│   └── .env                # (Optional) Client-specific Gmail / SMTP credentials
│
├── your_new_client/        # Your second product or client
│   ├── harvey.yaml
│   ├── skills/
│   ├── data/
│   └── .env
│
└── _template/              # Starter scaffold for new workspaces
```

---

## 🚀 Quick Commands

### 1. List all workspaces
```bash
harvey workspace list
```

### 2. Create a new product workspace
```bash
# Manual setup (from template)
harvey workspace new my_product

# Or automatically train from a product website URL:
harvey workspace new my_product --url https://myproduct.com
```

### 3. Check workspace details
```bash
harvey workspace info trackkaro
```

### 4. Run Harvey for a specific workspace
You have 3 easy ways:

**Option A — Using the `-w` flag (from project root):**
```bash
# Run outreach engine
harvey run -w trackkaro

# Launch web dashboard (localhost:5555)
harvey dashboard -w trackkaro --port 5555

# Run for second client on a different port (localhost:5556)
harvey dashboard -w my_product --port 5556
```

**Option B — By `cd` into the workspace folder:**
```bash
cd workspaces/trackkaro
harvey run
```

**Option C — Using environment variable:**
```bash
export HARVEY_WORKSPACE=trackkaro
harvey run
```
