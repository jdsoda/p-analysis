# P-ANALYSIS — Railway Deploy Guide

## Files List
```
p-analysis/
├── app.py              ← Flask main app
├── analyze.py          ← PDF analysis engine
├── export.py           ← Excel export engine
├── requirements.txt    ← Python packages
├── Procfile            ← Railway start command
├── railway.json        ← Railway config
├── .gitignore
└── templates/
    ├── login.html
    └── dashboard.html
```

---

## Step-by-Step Deploy

### Step 1 — GitHub Account
1. https://github.com కి వెళ్ళి account create చేయండి (free)

### Step 2 — New Repository
1. GitHub లో "+" → "New repository"
2. Name: `p-analysis`
3. Private గా పెట్టండి ✅
4. "Create repository" click

### Step 3 — Files Upload
1. Repository లో "uploading an existing file" click
2. ఈ folder లో అన్ని files select చేసి drag & drop
3. "Commit changes" click

### Step 4 — Railway Account
1. https://railway.app వెళ్ళి "Login with GitHub" చేయండి

### Step 5 — Deploy
1. Railway dashboard లో "New Project"
2. "Deploy from GitHub repo" select
3. `p-analysis` repo select చేయండి
4. Railway automatically deploy చేస్తుంది ✅

### Step 6 — Password Set చేయండి
Railway project లో:
1. "Variables" tab click
2. `APP_PASSWORD` = మీ password (e.g. `MyCA@2024`)
3. `SECRET_KEY` = random string (e.g. `xk92mPanalysis2024`)
4. "Deploy" automatically restart అవుతుంది

### Step 7 — Domain
1. Railway లో "Settings" → "Domains"
2. "Generate Domain" click
3. మీకు `p-analysis-xxxx.up.railway.app` లాంటి URL వస్తుంది
4. ఈ link share చేయండి — అందరూ access చేయవచ్చు!

---

## Password మార్చాలంటే
Railway → Variables → `APP_PASSWORD` update చేయండి
Code change అవసరం లేదు!

---

## Pricing
- Railway Free Tier: $5 credit/month (మన tool కి sufficient)
- 50+ CA offices వాడినా ~$5–10/month మాత్రమే
