FROM alpine:3.21

ENV PATH="/root/.local/bin:${PATH}"
WORKDIR /app

RUN apk add --no-cache curl tzdata ffmpeg && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    uv python install 3.10

COPY . .
RUN chmod +x ./scripts/*.sh

ENTRYPOINT ["sh"]