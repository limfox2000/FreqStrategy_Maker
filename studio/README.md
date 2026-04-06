# Freqtrade Strategy Studio (MVP)

## 1. 目录说明

1. `studio/api`：FastAPI 后端，提供模块生成、策略合成、回测运行和结果查询接口。  
2. `studio/web`：React + Three.js (R3F) 前端工作台。  
3. `freqtrade/user_data/tools/mvp_backtest_runner.py`：容器内回测执行脚本。  

## 2. 运行前提

1. Python 3.10+  
2. Node.js 18+  
3. Docker Desktop（用于容器内执行 freqtrade 策略回测）  
4. 本地已存在 freqtrade 数据目录（本仓库已包含 `freqtrade/user_data/data`）  

## 3. 启动后端

```powershell
cd g:\Trading\FreqStrategy_Maker\studio\api
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

健康检查：

```powershell
curl http://127.0.0.1:8000/api/health
```

## 4. 启动前端

```powershell
cd g:\Trading\FreqStrategy_Maker\studio\web
npm install
npm run dev
```

访问：`http://127.0.0.1:5173`

## 5. MVP 使用流程

1. 在 3D 装配区选中模块卡（指标因子 / 仓位调整 / 风险系统）。  
2. 输入需求，点击“生成当前模块”。  
3. 三张卡都生成后，点击“合成策略”。  
4. 设置交易对、周期、回测区间，点击“测试回测”。  
5. 等待任务完成后查看 K 线、权益曲线、回撤曲线与日志。  

## 6. 当前实现说明

1. 策略代码以 freqtrade `IStrategy` 格式生成并落盘到：
   `freqtrade/user_data/strategies/generated/`
2. 回测执行通过 Docker 容器运行 `mvp_backtest_runner.py`，输出结果到：
   `freqtrade/user_data/backtest_results/mvp_*.json`
3. 结果接口：`GET /api/backtest/{job_id}/result`

