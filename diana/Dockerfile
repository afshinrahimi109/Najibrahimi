# 🐠 Diana — اجرای داکری (برای هر هاست ابری رایگان که داکر پشتیبانی کند)
FROM python:3.12-slim
WORKDIR /app
COPY . /app
# هیچ نیازی به pip install نیست — فقط کتابخانه استاندارد پایتون!
ENV PORT=8000
EXPOSE 8000
VOLUME ["/app/data"]
CMD ["python3", "server.py"]
