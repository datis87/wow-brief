    def make_body():
        return json.dumps({"contents": [{"parts": [{"text": PROMPT + json.dumps(batch)}]}],
                           "generationConfig": {"responseMimeType": "application/json"}}).encode()
    raw = None
    models = pick_models()
    for rnd in range(3):
        if rnd == 2:
            for i in batch:
                i["text"] = i.get("text", "")[:1500]
        body = make_body()
        for model in models:
            try:
                raw = get(API + "/" + model + ":generateContent", body,
                          {"Content-Type": "application/json", "x-goog-api-key": KEY}, timeout=120)
                print("Used model:", model, "round", rnd)
                break
            except urllib.error.HTTPError as e:
                print(model, "round", rnd, e)
            except Exception as e:
                print(model, "round", rnd, e)
        if raw:
            break
        if rnd < 2:
            print("All models failed, waiting", 60 * (rnd + 1), "seconds")
            time.sleep(60 * (rnd + 1))
    if not raw:
        raise SystemExit("Gemini unavailable, will retry next run")
