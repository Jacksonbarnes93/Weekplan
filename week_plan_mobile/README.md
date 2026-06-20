# 📅 WeekPlan: AI-Powered Canvas Scheduler

WeekPlan is a full-stack scheduling pipeline designed to intelligently map out college coursework. It directly integrates with the Canvas LMS API to pull active assignments, applies a custom Python-based productivity algorithm, and generates a time-blocked study schedule on a cross-platform Flutter mobile application.

## 🚀 Tech Stack
* **Frontend:** Flutter / Dart
* **Backend:** Python / FastAPI
* **Integration:** Canvas LMS REST API

## 📂 Project Structure
This is a mono-repo containing both the mobile client and the API server.
* `/week_plan_mobile` - The Flutter mobile application.
* `/Backend` - The FastAPI Python server and scheduling algorithm.

---

## 🛠️ Local Setup & Installation

### 1. Python Backend Setup
The backend requires Python 3.9+ and uses Uvicorn to run the FastAPI server.

```bash
cd Backend
pip install fastapi uvicorn requests
uvicorn main:app --host 0.0.0.0 --port 8000 --reload