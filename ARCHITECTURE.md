# EV Taxi Image Validator (`checkin-out-services`)

## 1. Overview
The `checkin-out-services` repository contains a production-ready, headless microservice designed to automate the check-in and check-out inspection process for Electric Vehicle (EV) taxis. 

Currently, the service processes uploaded images through the Google Gemini Vision API to validate the images and provide a baseline assessment. As the project evolves, this service will be expanded to detect specific attributes such as battery dashboard readings, exterior damages, and interior cleanliness.

---

## 2. System Architecture

### Tech Stack
- **Web Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python) for ultra-fast, asynchronous API routing and request validation.
- **AI Engine:** Google Gemini Vision API via the `google-generativeai` Python SDK.
- **Image Processing:** `Pillow` (PIL) for in-memory image sanitization and compression.
- **Package Manager:** `uv` for blazingly fast dependency resolution and isolated CI/CD builds.

### Infrastructure (Tribore-AI)
- **Containerization:** Docker (Standardized organizational template).
- **Deployment:** Google Cloud Run (Serverless, auto-scaling, scale-to-zero capability).
- **Routing:** Handled by the organizational Load Balancer / API Gateway.
- **Secrets Management:** Google Secret Manager securely injects sensitive credentials like `GOOGLE_API_KEY` directly into the container's environment variables at runtime.

---

## 3. The Data Flow & Preprocessing Pipeline

To ensure the AI API calls are both highly performant and cost-effective, the backend does not forward raw user uploads directly to Gemini. Instead, it processes them through a strict pipeline:

1. **Request:** A client (mobile app or web dashboard) sends a `POST` request with a batch of images.
2. **Memory Buffer:** FastAPI receives the files as `UploadFile` objects and reads them directly into memory (avoiding slow disk I/O).
3. **Sanitization (Pillow):**
   - The image is converted to a standard `RGB` format (stripping out alpha channels or unsupported color spaces).
   - The image is dimensionally clamped. If it exceeds `1024x1024`, it is proportionally downscaled using the high-quality `LANCZOS` resampling filter.
   - The image is compressed and converted into a standard `JPEG` byte stream.
4. **AI Execution:** The optimized JPEGs are bundled with a system prompt and dispatched to the Gemini model.
5. **Response:** Gemini evaluates the batch and returns a structured JSON payload, which FastAPI forwards back to the client.

---

## 4. Image Validation Capabilities & Detection logic

The service natively supports batch image processing. When a client uploads multiple photos in a single request, each image is processed sequentially, and the Gemini model runs specific validation tests.

### What the API Currently Detects & Validates:
1. **Vehicle Presence:** Verifies if the image actually contains an EV taxi or a vehicle component. Non-car objects are rejected.
2. **Image Quality & Blur:** Checks for motion blur, low light, or severe camera shaking. Blurry images are rejected.
3. **Index Tracking:** Maps each result back to the exact order of the upload array using a 1-indexed count (`index`).

---

## 5. API Endpoints

### Core Endpoint: `POST /validate`
This is the primary endpoint for the AI validation service.

* **URL:** `https://api-nprd.driversklub.in/checkin-out-services/validate`
* **Method:** `POST`
* **Content-Type:** `multipart/form-data`
* **Parameters:** 
  * `files` (Required): An array of image files.

#### Example Batch Success Response (200 OK)
Below is an example response when uploading a batch of 4 files containing two valid EV taxi photos, a picture of a coffee cup (non-vehicle), and a blurry dashboard photo:

```json
{
  "success": true,
  "results": [
    {
      "index": 1,
      "valid": true,
      "reason": null
    },
    {
      "index": 2,
      "valid": true,
      "reason": null
    },
    {
      "index": 3,
      "valid": false,
      "reason": "Not a vehicle"
    },
    {
      "index": 4,
      "valid": false,
      "reason": "Too blurry due to motion blur"
    }
  ]
}
```

#### Example Error Responses
* **`400 Bad Request`**: Returned if the `files` array is completely empty, or if an uploaded file is not a valid image format that Pillow can read.
* **`422 Unprocessable Entity`**: Returned by FastAPI if the request is improperly formatted (e.g., missing the `files` field entirely).
* **`500 Internal Server Error`**: Returned if the backend fails to reach the Gemini API (e.g., missing API key or Google Cloud timeout).

---

### Utility Endpoints
These endpoints are primarily used by the Google Cloud Load Balancer to monitor the health of the container.
- `GET /`: Returns `{"message": "Hello, World!"}`.
- `GET /healthz`: Returns `{"status": "ok"}` for Load Balancer health checks.
- `GET /docs`: Automatically generated Swagger UI documentation (available when running locally).

---

## 6. Client Integration Guide

Integrating with this API requires sending a standard multipart form request. Below is a production-ready example using modern JavaScript (`fetch`).

### JavaScript (`fetch`) Example
```javascript
async function validateTaxiImages(imageFiles) {
  const formData = new FormData();
  
  // Append all selected images to the 'files' key
  // imageFiles should be an array of File objects from an <input type="file">
  for (let i = 0; i < imageFiles.length; i++) {
    formData.append("files", imageFiles[i]);
  }

  try {
    const response = await fetch("https://api-nprd.driversklub.in/checkin-out-services/validate", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    const aiAssessment = await response.json();
    console.log("Validation Results:", aiAssessment);
    return aiAssessment;

  } catch (error) {
    console.error("Failed to validate images:", error);
    // Add custom error handling for the frontend here
  }
}
```

---

## 7. Local Development & CI/CD

### Running Locally
To run the service locally for development or testing:
1. Ensure `uv` is installed.
2. Install dependencies: `uv sync`
3. Create a `.env` file and populate `GOOGLE_API_KEY`.
4. Run the server: `uv run uvicorn app.main:app --reload`
5. Visit `http://localhost:8000/docs` to test via the Swagger UI.

### CI/CD Pipeline
This microservice is deeply integrated into the `Tribore-AI` infrastructure:

1. **Linting & Validation:** On every Pull Request, GitHub Actions executes `uv run ruff check .` to enforce strict Python standards, ensuring code quality and preventing regressions.
2. **Continuous Deployment:** On a push to the `main` branch, the `deploy.yml` workflow automatically builds the Docker container and pushes it to Google Artifact Registry.
3. **Terraform Integration:** The infrastructure is governed by the central `platform-infra` repository. 
   - The API Gateway routes `/checkin-out-services/*` directly to this Cloud Run container.
   - Secrets are explicitly managed and dynamically injected, keeping the codebase completely free of hardcoded credentials.
