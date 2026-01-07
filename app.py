from flask import Flask
from flask_cors import CORS

app = Flask(__name__)

CORS(app, origins=[
    "https://lucasveiga02.github.io/killergame-frontend/",   # autorise GitHub Pages
])

@app.get("/")
def health():
    return "Backend is running"

if __name__ == "__main__":
    app.run()
