运行指令V1
cd D:\1HKUST\5110\ProjectV2
python -m uvicorn main:app --host 127.0.0.1 --port 8001

运行指令V2
conda activate nutribase
python -m uvicorn main:app --host 127.0.0.1 --port 8001

访问网址
http://127.0.0.1:8001/docs
