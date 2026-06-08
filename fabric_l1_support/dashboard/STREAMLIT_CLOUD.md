# Publish the Dashboard on Streamlit Community Cloud (free, public)

This gives you a permanent public URL like `https://<your-app>.streamlit.app`
that anyone can open — perfect for a LinkedIn post. No login, no Azure, free.

The dashboard automatically shows **sample data** when no real audit log is
present (which is the case on the cloud), so it looks great out of the box.
Do **not** add real credentials to a public app.

## One-time deploy (≈3 minutes)

1. Go to **https://share.streamlit.io** and click **Sign in with GitHub**
   (authorize it to read your repos).

2. Click **Create app → Deploy a public app from GitHub**.

3. Fill in:
   | Field | Value |
   |-------|-------|
   | **Repository** | `lakshmijs222/fabric-pipeline-agent` |
   | **Branch** | `master` |
   | **Main file path** | `fabric_l1_support/dashboard/app.py` |

4. (Optional) Click **Advanced settings** and set **App URL** to something
   clean like `fabric-pipeline-agent` → your link becomes
   `https://fabric-pipeline-agent.streamlit.app`.

5. Click **Deploy**. First build takes ~2 minutes while it installs the
   dependencies from `fabric_l1_support/dashboard/requirements.txt`.

That's it — copy the URL into your LinkedIn post. 🎉

## Notes
- **Auto-updates:** every time you `git push`, Streamlit Cloud redeploys.
- **"Total Pipelines" card** shows `—` here because it needs live Azure
  credentials, which (correctly) are not present in a public demo.
- **No secrets needed.** If you ever *did* want live data, you'd add keys under
  the app's **Settings → Secrets** — but never do that for a public showcase.
- If the app sleeps after inactivity, the first visitor's load wakes it in a
  few seconds.
