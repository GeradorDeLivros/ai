# Use the official Python image from the Docker Hub
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file
COPY requirements.txt .

# Install any dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production  # Ensure Flask runs in production mode
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5151

# Install Gunicorn (production-ready server)
RUN pip install gunicorn

# Expose the port the app runs on
EXPOSE 5151

# Run the Flask app using Gunicorn (which is production-ready)
CMD ["gunicorn", "-b", "0.0.0.0:5151", "app:app"]
