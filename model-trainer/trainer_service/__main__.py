import uvicorn

if __name__ == '__main__':
    uvicorn.run("model_trainer.trainer_service.server:app", host="0.0.0.0", port=8088, reload=False)

