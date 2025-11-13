import uvicorn

if __name__ == '__main__':
    # 正确的模块路径应为 trainer_service.server:app
    uvicorn.run("trainer_service.server:app", host="0.0.0.0", port=8088, reload=False)
