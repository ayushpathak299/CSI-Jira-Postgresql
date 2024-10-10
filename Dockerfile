FROM tiangolo/uwsgi-nginx:python3.9

# Install required packages
RUN pip3 install requests psycopg2

# Set the working directory
WORKDIR /app

# Copy all files to the container
COPY . /app/

# Define the command to run your application
CMD ["python", "/app/main.py"]
