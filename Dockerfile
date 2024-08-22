FROM python:3.12-slim

RUN python3 -m venv venv

COPY requirements.txt ./
RUN pip install -r ./requirements.txt

COPY . ./

CMD ["python", "run.py"]