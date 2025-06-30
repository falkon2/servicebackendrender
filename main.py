#!/usr/bin/env python3
"""
Secure FastAPI Backend for Reddit OAuth2 Web App

This backend implements OAuth2 Authorization Code Flow for secure Reddit authentication.
Users authenticate through Reddit's OAuth2 flow without exposing credentials. working!
"""

import os
import secrets
import httpx
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime, timedelta
import base64
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Reddit OAuth2 API",
    description="Secure Reddit API using OAuth2 Authorization Code Flow",
    version="2.0.0"
)

# Environment variables
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_REDIRECT_URI = os.getenv("REDDIT_REDIRECT_URI")  # Should be your backend /callback URL
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Validate required environment variables
required_vars = ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_REDIRECT_URI"]
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {missing_vars}")

# CORS configuration
origins = [
    "http://localhost:3000",
    "https://redditstatschecker.onrender.com",  # Your frontend URL
    FRONTEND_URL
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (use Redis in production)
sessions: Dict[str, Dict[str, Any]] = {}

# Reddit API endpoints
REDDIT_AUTHORIZE_URL = "https://www.reddit.com/api/v1/authorize"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API_BASE = "https://oauth.reddit.com"

# Pydantic models
class UserProfile(BaseModel):
    username: str
    total_karma: int
    link_karma: int
    comment_karma: int
    account_created: str
    total_posts: int
    total_comments: int

class Post(BaseModel):
    title: str
    subreddit: str
    score: int
    num_comments: int
    created_utc: float
    created_time: str
    permalink: str
    url: str
    selftext: Optional[str] = None

class Comment(BaseModel):
    subreddit: str
    post_title: str
    score: int
    created_utc: float
    created_time: str
    body: str
    permalink: str

class AuthResponse(BaseModel):
    auth_url: str
    state: str

def generate_state() -> str:
    """Generate a secure random state parameter for OAuth2"""
    return secrets.token_urlsafe(32)

def create_auth_url(state: str) -> str:
    """Create Reddit OAuth2 authorization URL"""
    scope = "identity read history"  # Minimal required scopes
    duration = "temporary"  # Only temporary access
    
    params = {
        "client_id": REDDIT_CLIENT_ID,
        "response_type": "code",
        "state": state,
        "redirect_uri": REDDIT_REDIRECT_URI,
        "duration": duration,
        "scope": scope
    }
    
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"{REDDIT_AUTHORIZE_URL}?{query_string}"

async def exchange_code_for_token(code: str) -> Dict[str, Any]:
    """Exchange authorization code for access token"""
    # Create basic auth header
    auth_string = f"{REDDIT_CLIENT_ID}:{REDDIT_CLIENT_SECRET}"
    auth_bytes = auth_string.encode('utf-8')
    auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')
    
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "User-Agent": "RedditOAuth2App/1.0"
    }
    
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDDIT_REDIRECT_URI
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            REDDIT_TOKEN_URL,
            headers=headers,
            data=data
        )
        
        if response.status_code != 200:
            logger.error(f"Token exchange failed: {response.status_code} {response.text}")
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")
        
        return response.json()

async def get_total_count(access_token: str, endpoint: str) -> int:
    """Get total count of posts or comments by fetching all pages"""
    total_count = 0
    after = None
    
    while True:
        # Build URL with pagination
        url = f"{endpoint}?limit=100"
        if after:
            url += f"&after={after}"
            
        data = await make_reddit_api_request(access_token, url)
        children = data["data"]["children"]
        
        if not children:
            break
            
        total_count += len(children)
        after = data["data"].get("after")
        
        if not after:
            break
            
    return total_count

async def make_reddit_api_request(access_token: str, endpoint: str) -> Dict[str, Any]:
    """Make authenticated request to Reddit API"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "RedditOAuth2App/1.0"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{REDDIT_API_BASE}{endpoint}", headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Reddit API request failed: {response.status_code} {response.text}")
            raise HTTPException(status_code=400, detail="Failed to fetch data from Reddit")
        
        return response.json()

@app.get("/")
async def root():
    """API information"""
    return {
        "message": "Reddit OAuth2 API",
        "version": "2.0.0",
        "auth_endpoint": "/auth/login",
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/auth/login", response_model=AuthResponse)
async def login():
    """Initiate OAuth2 flow - returns Reddit authorization URL"""
    state = generate_state()
    auth_url = create_auth_url(state)
    
    # Store state for validation (in production, use Redis with expiration)
    sessions[state] = {
        "created_at": datetime.utcnow(),
        "used": False
    }
    
    return AuthResponse(auth_url=auth_url, state=state)

@app.get("/auth/callback")
async def auth_callback(code: str, state: str, error: Optional[str] = None):
    """OAuth2 callback endpoint - Reddit redirects here after user authorization"""
    
    if error:
        logger.error(f"OAuth2 error: {error}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?error={error}",
            status_code=302
        )
    
    # Validate state parameter
    if state not in sessions or sessions[state]["used"]:
        logger.error(f"Invalid or used state: {state}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?error=invalid_state",
            status_code=302
        )
    
    # Mark state as used
    sessions[state]["used"] = True
    
    try:
        # Exchange code for access token
        token_data = await exchange_code_for_token(code)
        access_token = token_data["access_token"]
        
        # Generate session ID
        session_id = secrets.token_urlsafe(32)
        
        # Store session (in production, use Redis with expiration)
        sessions[session_id] = {
            "access_token": access_token,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 3600))
        }
        
        # Redirect to frontend with session ID
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?session={session_id}",
            status_code=302
        )
        
    except Exception as e:
        logger.error(f"Callback error: {str(e)}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?error=callback_failed",
            status_code=302
        )

def get_session(session_id: str) -> Dict[str, Any]:
    """Get and validate session"""
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    session = sessions[session_id]
    
    # Check if session is expired
    if datetime.utcnow() > session.get("expires_at", datetime.utcnow()):
        del sessions[session_id]
        raise HTTPException(status_code=401, detail="Session expired")
    
    return session

@app.get("/api/profile", response_model=UserProfile)
async def get_user_profile(session_id: str):
    """Get user profile information"""
    session = get_session(session_id)
    access_token = session["access_token"]
    
    try:
        # Get user identity
        me_data = await make_reddit_api_request(access_token, "/api/v1/me")
        
        # Get user posts count (get all posts to count them properly)
        posts_count = await get_total_count(access_token, "/user/self/submitted")
        
        # Get user comments count (get all comments to count them properly)
        comments_count = await get_total_count(access_token, "/user/self/comments")
        
        created_utc = me_data.get("created_utc", 0)
        created_date = datetime.fromtimestamp(created_utc).strftime('%Y-%m-%d') if created_utc else "Unknown"
        
        return UserProfile(
            username=me_data.get("name", "Unknown"),
            total_karma=me_data.get("total_karma", 0),
            link_karma=me_data.get("link_karma", 0),
            comment_karma=me_data.get("comment_karma", 0),
            account_created=created_date,
            total_posts=posts_count,
            total_comments=comments_count
        )
        
    except Exception as e:
        logger.error(f"Profile fetch error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch profile")

@app.get("/api/posts", response_model=List[Post])
async def get_user_posts(session_id: str, limit: int = 10):
    """Get user's recent posts"""
    session = get_session(session_id)
    access_token = session["access_token"]
    
    try:
        posts_data = await make_reddit_api_request(
            access_token, 
            f"/user/self/submitted?limit={min(limit, 25)}"
        )
        
        posts = []
        for post_data in posts_data["data"]["children"]:
            post = post_data["data"]
            created_time = datetime.fromtimestamp(post["created_utc"]).strftime('%Y-%m-%d %H:%M:%S')
            
            posts.append(Post(
                title=post.get("title", ""),
                subreddit=post.get("subreddit", ""),
                score=post.get("score", 0),
                num_comments=post.get("num_comments", 0),
                created_utc=post.get("created_utc", 0),
                created_time=created_time,
                permalink=f"https://reddit.com{post.get('permalink', '')}",
                url=post.get("url", ""),
                selftext=post.get("selftext", None) if post.get("selftext") else None
            ))
        
        return posts
        
    except Exception as e:
        logger.error(f"Posts fetch error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch posts")

@app.get("/api/comments", response_model=List[Comment])
async def get_user_comments(session_id: str, limit: int = 10):
    """Get user's recent comments"""
    session = get_session(session_id)
    access_token = session["access_token"]
    
    try:
        comments_data = await make_reddit_api_request(
            access_token,
            f"/user/self/comments?limit={min(limit, 25)}"
        )
        
        comments = []
        for comment_data in comments_data["data"]["children"]:
            comment = comment_data["data"]
            created_time = datetime.fromtimestamp(comment["created_utc"]).strftime('%Y-%m-%d %H:%M:%S')
            
            comments.append(Comment(
                subreddit=comment.get("subreddit", ""),
                post_title=comment.get("link_title", "Unknown Post"),
                score=comment.get("score", 0),
                created_utc=comment.get("created_utc", 0),
                created_time=created_time,
                body=comment.get("body", ""),
                permalink=f"https://reddit.com{comment.get('permalink', '')}"
            ))
        
        return comments
        
    except Exception as e:
        logger.error(f"Comments fetch error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch comments")

@app.delete("/auth/logout")
async def logout(session_id: str):
    """Logout user by invalidating session"""
    if session_id in sessions:
        del sessions[session_id]
    
    return {"message": "Logged out successfully"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
