from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>AI Chat</title>
<style>
body{margin:0;background:#f2f2f2;font-family:system-ui}
.chat{max-width:600px;height:100vh;margin:auto;display:flex;flex-direction:column;background:#fff}
header{padding:10px;border-bottom:1px solid #ddd}
select{width:100%;padding:8px}
.messages{flex:1;overflow-y:auto;padding:10px}
.msg{padding:10px;border-radius:14px;margin:6px 0;max-width:80%}
.user{background:#007aff;color:#fff;margin-left:auto}
.ai{background:#e5e5ea}
form{display:flex;padding:10px;border-top:1px solid #ddd}
input{flex:1;padding:10px;border-radius:20px;border:1px solid #ccc}
button{margin-left:8px;padding:10px 16px;border:none;border-radius:20px;background:#007aff;color:#fff}
</style>
</head>
<body>
<div class=chat>
<header>
<select id=personality>
<option value="You are a friendly assistant.">Friendly</option>
<option value="You are sarcastic and witty.">Sarcastic</option>
<option value="You are a professional mentor.">Mentor</option>
<option value="You are an anime-style character.">Anime</option>
</select>
</header>
<div class=messages id=chat></div>
<form id=form>
<input id=input placeholder="Type a message" autocomplete=off>
<button>Send</button>
</form>
</div>

<script>
let history=[]
const chat=document.getElementById("chat")
const form=document.getElementById("form")
const input=document.getElementById("input")
const personality=document.getElementById("personality")

function add(text,type){
 const d=document.createElement("div")
 d.className="msg "+type
 d.innerText=text
 chat.appendChild(d)
 chat.scrollTop=chat.scrollHeight
}

form.onsubmit=async e=>{
 e.preventDefault()
 if(!input.value.trim())return
 const msg=input.value
 add(msg,"user")
 history.push({role:"user",content:msg})
 input.value=""
 const r=await fetch("/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:msg,personality:personality.value,history})})
 const j=await r.json()
 add(j.reply,"ai")
 history.push({role:"assistant",content:j.reply})
}
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return HTML

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": data["personality"]},
                *data["history"],
                {"role": "user", "content": data["message"]}
            ]
        }
    )
    return jsonify(reply=r.json()["choices"][0]["message"]["content"])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
