# crew-chief — Podman container for the local Ollama LLM service
#
# Build:
#   podman build -t crew-chief:latest .
#
# Run via scripts/start.sh or directly:
#   podman run -d --name crew-chief -p 11434:11434 \
#       -v crew-chief-models:/root/.ollama crew-chief:latest

FROM docker.io/ollama/ollama:latest

EXPOSE 11434

ENTRYPOINT ["ollama", "serve"]
