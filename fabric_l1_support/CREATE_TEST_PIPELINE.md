# Create a Flaky (Network-Failing) Test Pipeline in Microsoft Fabric

Goal: build a real Fabric Data Pipeline that **fails with a network error**, so when you
run `start.bat` the L1 bot detects it, diagnoses it as *transient*, and **reruns it** —
and because the endpoint is flaky, the rerun succeeds → **auto-fixed**. ✅

---

## Why this works

We point a **Web activity** at a random-status endpoint:

```
https://httpstat.us/random/200,200,200,503,504
```

| Returned status | Result            |
|-----------------|-------------------|
| 200 OK (60%)    | Pipeline succeeds |
| 503 / 504 (40%) | Pipeline FAILS — looks like a gateway/network outage |

The bot reruns failed runs up to 3×. With 60% success per try, a rerun almost always
lands on 200 → the bot reports **AUTO-FIXED**.

---

## Step-by-step (Fabric Portal UI)

### 1. Open your workspace
- Go to **https://app.fabric.microsoft.com**
- Open the workspace whose ID is in your `.env`:
  `a078c6ff-84af-4f0e-b177-381e4bba48ee`

### 2. Create the Data Pipeline
- Click **+ New item** (or **New** → **Data pipeline**)
- Name it: **`Network_Flaky_Test`**
- Click **Create**

### 3. Add a Web activity
- In the pipeline canvas, from the **Activities** ribbon, search **Web** and drag it in
  (under *General* → **Web**).
- Click the new Web activity → open the **Settings** tab.

### 4. Configure the Web activity
| Field      | Value                                            |
|------------|--------------------------------------------------|
| **URL**    | `https://httpstat.us/random/200,200,200,503,504` |
| **Method** | `GET`                                            |
| **Headers**| *(leave empty)*                                  |

> A Web activity treats any non-2xx response (503/504) as a **failure**, which fails the
> whole pipeline. That's exactly what we want.

### 5. (Recommended) Tighten the timeout so failures are fast
- On the Web activity, open the **General** tab.
- Set **Timeout** to `0.00:02:00` (2 minutes) and **Retry** to `0`
  (we want the *bot* to handle retries, not the activity itself).

### 6. Save & run it
- Click **Save** (top ribbon).
- Click **▶ Run**.
- Run it **several times** (3–5×) until you see at least one **Failed** run in the
  **Output** / run history. (Each run is an independent dice roll.)

You now have a real failed pipeline run in Fabric. 🎯

---

## 7. Let the bot fix it

Back on your machine:

```powershell
cd D:\Claude\fabric-l1-bot
.\start.bat
```

Watch the console. You should see roughly:

```
Poll cycle starting...
Workspace a078c6ff...: 1 new failures found
Diagnosing pipeline Network_Flaky_Test ...
Auto-fixing pipeline Network_Flaky_Test (attempt 1/3)
Pipeline Network_Flaky_Test rerun triggered. Run ID: <new-run-id>
Handled Network_Flaky_Test/...: auto_rerun | success=True
```

Then open the new run in Fabric — it most likely shows **Succeeded** (rolled a 200).

---

## 8. See it in the dashboard
Open the Streamlit dashboard (or `start_dashboard_only.bat`) — the incident appears as a
green **AUTO-FIXED** card, and the audit log records the action.

---

## Notes / Tips
- **Always escalates instead of fixing?** You got unlucky on the dice, or the endpoint
  was down. Re-run, or bias success higher: `https://httpstat.us/random/200,200,200,200,503`.
- **Want a guaranteed single failure** (no auto-fix, to test escalation)? Use a permanently
  bad URL like `https://httpstat.us/504` — it fails every rerun → bot escalates after 3 tries.
- **Want a pure timeout (true network hang)?** Use `https://httpstat.us/200?sleep=300000`
  (sleeps 5 min) with the activity **Timeout** set to `0.00:01:00` → times out every time.
