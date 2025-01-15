FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5151

# Install Gunicorn (production-ready server)
RUN pip install gunicorn

# Expose the port the app runs on
EXPOSE 5151

# Run the Flask app using Gunicorn (which is production-ready)
CMD ["gunicorn", "-b", "0.0.0.0:5151", "app:app"]
