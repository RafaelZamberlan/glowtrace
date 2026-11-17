# easyapi (Python)

See your FastAPI app as an n8n-style flow and watch every request run through it.

```python
from fastapi import FastAPI
from easyapi import EasyAPI

app = FastAPI()
EasyAPI(app)  # open http://127.0.0.1:8000/_easyapi/
```

See the repository README for full documentation.
