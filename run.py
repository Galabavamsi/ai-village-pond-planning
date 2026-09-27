import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("POND_HOST", "127.0.0.1"),
        port=int(os.getenv("POND_PORT", "8000")),
        reload=False,
    )
