"""
BizFlow — запуск (entrypoint).

Windows PowerShell:
  py -3 -m pip install -r requirements.txt
  py -3 .\run.py
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

