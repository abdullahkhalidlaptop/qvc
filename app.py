import os, time, json, threading, asyncio
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template_string, send_from_directory
from playwright.async_api import async_playwright

URL = "https://www.qatarvisacenter.com/"
WAIT_TIME = 3
POLL_INTERVAL = 2   # poll every 2 seconds
STATIC_DIR = "static"

os.makedirs(STATIC_DIR, exist_ok=True)
STATUS_PATH = os.path.join(STATIC_DIR, "status.json")
LOG_PATH = os.path.join(STATIC_DIR, "logs.txt")
LATEST_SCREENSHOT = os.path.join(STATIC_DIR, "latest.png")
CAPTCHA_IMAGE = os.path.join(STATIC_DIR, "captcha.png")
CAPTCHA_SOLUTION_FILE = os.path.join(STATIC_DIR, "captcha_solution.txt")

shared_state = {"phase":"idle","current_url":"","error":"","date_found":False,"date_matches":[]}
LOG_HISTORY = []
last_no_date_msg = ""

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    global last_no_date_msg
    if "No dates yet" in msg:
        if last_no_date_msg == msg and LOG_HISTORY:
            LOG_HISTORY[-1] = line
        else:
            LOG_HISTORY.append(line)
            last_no_date_msg = msg
    else:
        LOG_HISTORY.append(line)
        last_no_date_msg = ""
    if len(LOG_HISTORY) > 3:
        LOG_HISTORY.pop(0)
    with open(LOG_PATH,"w") as f:
        f.write("\n".join(LOG_HISTORY))
    print(line)
    shared_state["last_update"]=ts
    with open(STATUS_PATH,"w") as f: json.dump(shared_state,f)

def read_credentials():
    creds={"PASSPORT":"","VISA":"","NUMBER":"","EMAIL":""}
    if os.path.exists("credentials.txt"):
        for line in open("credentials.txt"):
            if "=" in line:
                k,v=line.strip().split("=",1)
                if k in creds: creds[k]=v
    return creds

async def capture_temp_screenshot(page):
    ts = int(time.time())
    path = os.path.join(STATIC_DIR, f"temp_{ts}.png")
    await page.screenshot(path=path)
    if os.path.exists(LATEST_SCREENSHOT):
        os.remove(LATEST_SCREENSHOT)
    os.rename(path, LATEST_SCREENSHOT)

async def detect_available_dates(page):
    slots = await page.query_selector_all(
        "td.datepicker__day:not(.is-disabled) button.datepicker__button:not([disabled])"
    )
    texts = [await s.inner_text() for s in slots]
    return texts

async def run_bot_forever():
    creds=read_credentials()
    passport_number=creds["PASSPORT"]
    visa_number=creds["VISA"]
    phone_number=creds["NUMBER"]
    email_address=creds["EMAIL"]

    while True:
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True)
                context=await browser.new_context(record_video_dir="videos/")
                page=await context.new_page()

                # Stealth headers
                await page.set_extra_http_headers({
                    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
                    "Accept-Language":"en-US,en;q=0.9"
                })
                await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")

                # Navigate
                shared_state["phase"]="navigate"
                await page.goto(URL,timeout=60000)
                await capture_temp_screenshot(page)
                log("✅ Page loaded")
                await asyncio.sleep(WAIT_TIME)

                # Language
                await page.click("input[placeholder='-- Select Language --']")
                await page.click("ul.dropdown-menu >> text=English")
                await capture_temp_screenshot(page)
                log("✅ English selected")
                await asyncio.sleep(WAIT_TIME)

                # Country
                await page.click("input[placeholder='-- Select Country --']")
                await page.click("ul.dropdown-menu >> text=Pakistan")
                await capture_temp_screenshot(page)
                log("✅ Pakistan selected")
                await asyncio.sleep(WAIT_TIME)

                # Book Appointment
                await page.click("a.card-box:has-text('Book Appointment')")
                await capture_temp_screenshot(page)
                log("✅ Book Appointment clicked")
                await asyncio.sleep(WAIT_TIME)

                # Mandatory OK
                await page.click("button.cir-em-btn:has-text('OK')")
                await capture_temp_screenshot(page)
                log("✅ Mandatory OK clicked")
                await asyncio.sleep(WAIT_TIME)

                # Passport/Visa
                await page.fill("input[placeholder='Passport Number']",passport_number)
                await page.fill("input[placeholder='Visa Number']",visa_number)
                await capture_temp_screenshot(page)
                log(f"🛂 Passport {passport_number}, Visa {visa_number}")
                await asyncio.sleep(WAIT_TIME)

                # Captcha
                cap_el=await page.query_selector("#captchaImage")
                if cap_el:
                    await cap_el.screenshot(path=CAPTCHA_IMAGE)
                    log("📸 Captcha captured immediately; waiting for solution")
                if os.path.exists(CAPTCHA_SOLUTION_FILE): os.remove(CAPTCHA_SOLUTION_FILE)
                while True:
                    await asyncio.sleep(1)
                    if os.path.exists(CAPTCHA_SOLUTION_FILE):
                        cap_val=open(CAPTCHA_SOLUTION_FILE).read().strip()
                        if cap_val: break
                await page.fill("input[name='captcha']",cap_val)
                log(f"✅ Captcha filled: {cap_val}")
                await asyncio.sleep(WAIT_TIME)

                # Submit
                await page.click("button.btn-brand-arrow")
                await capture_temp_screenshot(page)
                log("✅ Submit clicked")
                await asyncio.sleep(WAIT_TIME)

                # Applicant details (patched selectors)
                try:
                    await page.click("button.cir-em-btn:has-text('OK')")
                    log("✅ Applicant OK clicked")
                except:
                    log("ℹ️ No Applicant OK popup")

                await page.wait_for_selector("#phone", timeout=60000)
                await page.fill("#phone", phone_number)
                log(f"📱 Primary phone filled: {phone_number}")

                await page.wait_for_selector("#email", timeout=60000)
                await page.fill("#email", email_address)
                log(f"📧 Primary email filled: {email_address}")

                try:
                    await page.check("#checkVal")
                    log("☑️ Primary contact checkbox ticked")
                except:
                    log("ℹ️ Checkbox not found or already ticked")

                await page.wait_for_selector("#contactNumber", timeout=60000)
                await page.fill("#contactNumber", phone_number)
                log(f"📱 Applicant contact number filled: {phone_number}")

                await page.wait_for_selector("#emailId", timeout=60000)
                await page.fill("#emailId", email_address)
                log(f"📧 Applicant email filled: {email_address}")

                await page.wait_for_selector("button.cir-sb-btn", timeout=60000)
                await page.click("button.cir-sb-btn")
                await capture_temp_screenshot(page)
                log("✅ Applicant confirmed")

                # Manage OK + Islamabad
                try:
                    await page.click("button.cir-em-btn:has-text('OK')")
                    log("✅ Manage OK clicked")
                except: pass
                await page.click("button[name='selectedVsc']")
                await page.click("text=Islamabad")
                await capture_temp_screenshot(page)
                log("✅ Islamabad selected")

                # Monitoring loop
                shared_state["phase"]="monitor"
                log("🕒 Monitoring slotdetails for available dates...")
                while True:
                    try:
                        await page.wait_for_load_state("domcontentloaded")
                        texts=await detect_available_dates(page)
                        await capture_temp_screenshot(page)
                        if texts:
                            ts=datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                            shot=os.path.join(STATIC_DIR,f"date_{ts}.png")
                            await page.screenshot(path=shot)
                            shared_state.update(date_found=True,date_matches=texts)
                            log(f"🔔 REAL DATE AVAILABLE! {texts}")
                        else:
                            shared_state.update(date_found=False,date_matches=[])
                            log("ℹ️ No dates yet")
                    except Exception as e:
                        shared_state["error"]=str(e)
                        log(f"⚠️ Error: {e}")
                        await asyncio.sleep(2)
                    await asyncio.sleep(POLL_INTERVAL)
        except Exception as e:
            shared_state["error"]=str(e)
            log(f"❌ Fatal error: {e}, restarting...")

# ------------------ Flask Dashboard ------------------
app = Flask(__name__, static_folder=STATIC_DIR)

DASHBOARD_HTML = """
<!doctype html>
<html>
<head>
  <title>QVC Bot Dashboard</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
  <style>
    body { background:#f8f9fa; }
    .screenshot { max-width:100%; border:2px solid #333; border-radius:8px; }
    .logs { height:300px; overflow:auto; background:#212529; color:#f8f9fa; padding:10px; border-radius:8px; font-family: monospace; }
    .captcha-card { background:#fff; padding:15px; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.2); }
  </style>
</head>
<body class="container py-4">
  <h1 class="mb-4 text-primary">QVC Bot Dashboard</h1>
  <div class="row">
    <div class="col-md-8">
      <h3>Live Screenshot</h3>
      <img src="/static/latest.png?ts={{ ts }}" class="screenshot"/>
    </div>
    <div class="col-md-4">
      <h3>Status</h3>
      <ul class="list-group">
        <li class="list-group-item">Phase: <span class="badge bg-info">{{ phase }}</span></li>
        <li class="list-group-item">URL: <code>{{ current_url }}</code></li>
        <li class="list-group-item">Last update: {{ last_update }}</li>
        <li class="list-group-item">Date found: {% if date_found %}<span class="badge bg-success">YES</span>{% else %}<span class="badge bg-secondary">NO</span>{% endif %}</li>
        <li class="list-group-item">Error: {{ error }}</li>
      </ul>
    </div>
  </div>
  <div class="row mt-4">
    <div class="col-md-8">
      <h3>Logs (last 3)</h3>
      <div class="logs">{{ logs }}</div>
    </div>
    <div class="col-md-4">
      <h3>Captcha</h3>
      <div class="captcha-card">
        <img src="/static/captcha.png?ts={{ ts }}" width="300" class="mb-2"/>
        <form action="/captcha" method="post">
          <input type="text" name="solution" class="form-control mb-2" placeholder="Enter captcha" required/>
          <button class="btn btn-primary w-100">Submit</button>
        </form>
      </div>
    </div>
  </div>
  <script>
    // Refresh only the screenshot every 2 seconds
    setInterval(()=>{
      const img = document.querySelector('img.screenshot');
      if(img){
        const url = new URL(img.src);
        url.searchParams.set('ts', Date.now());
        img.src = url.toString();
      }
    }, 2000);
  </script>
</body>
</html>
"""

@app.route("/")
def root():
    return redirect(url_for("dashboard"))

@app.route("/dashboard")
def dashboard():
    try:
        logs = open(LOG_PATH).read()
    except:
        logs = "(no logs yet)"
    try:
        status = json.load(open(STATUS_PATH))
    except:
        status = shared_state
    return render_template_string(
        DASHBOARD_HTML,
        logs=logs,
        ts=int(time.time()),
        phase=status.get("phase","idle"),
        current_url=status.get("current_url",""),
        last_update=status.get("last_update",""),
        date_found=status.get("date_found",False),
        error=status.get("error","")
    )

@app.route("/captcha", methods=["POST"])
def captcha():
    sol = request.form.get("solution","").strip()
    if sol:
        open(CAPTCHA_SOLUTION_FILE,"w").write(sol)
        log(f"🔑 Captcha solution received: {sol}")
    return redirect(url_for("dashboard"))

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)

# ------------------ Entrypoint ------------------
def start_bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot_forever())

if __name__ == "__main__":
    if not os.path.exists(LOG_PATH):
        open(LOG_PATH,"w").close()
    threading.Thread(target=start_bot_thread, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
