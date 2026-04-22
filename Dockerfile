FROM python:3.12-slim
WORKDIR /stt-docker

# Install locales
RUN apt-get update --fix-missing \
    && apt-get install -y locales \
    && sed -i 's/# ru_RU.UTF-8 UTF-8/ru_RU.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen ru_RU.UTF-8 \
    && update-locale LANG=ru_RU.UTF-8

# Set environment variables
ENV LANG ru_RU.UTF-8
ENV LANGUAGE ru_RU:ru
ENV LC_ALL ru_RU.UTF-8

COPY requirements.txt requirements.txt
RUN python -m pip install -r requirements.txt

COPY . .
#EXPOSE 5000

#CMD ["python", "app.py"]
#CMD [ "python3", "-m" , "flask", "run", "--host=0.0.0.0"]
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
