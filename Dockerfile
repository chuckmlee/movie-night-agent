FROM python:3.12-slim
WORKDIR /app
COPY movie_night ./movie_night
COPY household ./household
ENV PYTHONUNBUFFERED=1 MNA_DATA=/data
# /data must be backed by a persistent Railway Volume (mounted in the service settings): it holds the film cache, agent state and session history.
EXPOSE 8080
CMD ["python3", "-m", "movie_night.serve"]
