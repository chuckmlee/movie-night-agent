FROM python:3.12-slim
WORKDIR /app
COPY movie_night ./movie_night
ENV PYTHONUNBUFFERED=1 MNA_DATA=/data
# /data should be a persistent volume: it holds the film cache, agent state and session history.
VOLUME /data
EXPOSE 8080
CMD ["python3", "-m", "movie_night.serve"]
