#!/usr/bin/env python3
"""
FastAPI Backend for Reddit Stats Website

This backend provides API endpoints for checking Reddit posts, comments, and user statistics
using PRAW (Python Reddit API Wrapper).
"""

import os
import praw
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import datetime
from typing import List, Optional, Dict, Any
import sys

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Reddit Stats API",
    description="API for retrieving Reddit user statistics, posts, and comments",
    version="1.0.0"
)

# Add CORS middleware to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for request/response
class RedditCredentials(BaseModel):
    client_id: str
    client_secret: str
    user_agent: str
    username: str
    password: str

class PostResponse(BaseModel):
    title: str
    subreddit: str
    score: int
    ups: int
    downs: int
    num_comments: int
    created_utc: float
    created_time: str
    permalink: str
    url: str
    selftext: Optional[str] = None
    content_preview: Optional[str] = None

class CommentResponse(BaseModel):
    subreddit: str
    post_title: str
    score: int
    created_utc: float
    created_time: str
    body: str
    comment_preview: str
    permalink: str
    url: str

class UserStats(BaseModel):
    username: str
    account_created: str
    link_karma: int
    comment_karma: int
    total_karma: int
    total_posts: int
    total_comments: int

class ErrorResponse(BaseModel):
    error: str
    message: str

# Global Reddit instance
reddit_instance = None

def get_reddit_instance():
    """
    Get or create Reddit instance using environment variables.
    """
    global reddit_instance
    
    if reddit_instance is not None:
        return reddit_instance
    
    # Get credentials from environment variables
    client_id = os.getenv('REDDIT_CLIENT_ID')
    client_secret = os.getenv('REDDIT_CLIENT_SECRET')
    user_agent = os.getenv('REDDIT_USER_AGENT')
    username = os.getenv('REDDIT_USERNAME')
    password = os.getenv('REDDIT_PASSWORD')
    
    # Check if all required credentials are provided
    if not all([client_id, client_secret, user_agent, username, password]):
        raise HTTPException(
            status_code=500, 
            detail="Missing Reddit API credentials in environment variables"
        )
    
    try:
        # Create Reddit instance
        reddit_instance = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            username=username,
            password=password
        )
        
        # Test the connection
        reddit_instance.user.me()
        return reddit_instance
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error connecting to Reddit: {str(e)}")

def create_reddit_instance_with_credentials(credentials: RedditCredentials):
    """
    Create Reddit instance with provided credentials.
    """
    try:
        reddit = praw.Reddit(
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            user_agent=credentials.user_agent,
            username=credentials.username,
            password=credentials.password
        )
        
        # Test the connection
        reddit.user.me()
        return reddit
        
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Error connecting to Reddit: {str(e)}")

@app.get("/")
def read_root():
    """
    Root endpoint with API information.
    """
    return {
        "message": "Welcome to the Reddit Stats Website API!",
        "version": "1.0.0",
        "endpoints": {
            "user_stats": "/api/user/stats",
            "posts": "/api/user/posts",
            "comments": "/api/user/comments",
            "health": "/health"
        }
    }

@app.get("/health")
def health_check():
    """
    Health check endpoint.
    """
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/user/stats", response_model=UserStats)
def get_user_stats(reddit: praw.Reddit = Depends(get_reddit_instance)):
    """
    Get user statistics including karma, account age, and activity counts.
    """
    try:
        user = reddit.user.me()
        
        # Count posts and comments
        post_count = sum(1 for _ in user.submissions.new(limit=None))
        comment_count = sum(1 for _ in user.comments.new(limit=None))
        
        return UserStats(
            username=user.name,
            account_created=datetime.fromtimestamp(user.created_utc).strftime('%Y-%m-%d'),
            link_karma=user.link_karma,
            comment_karma=user.comment_karma,
            total_karma=user.link_karma + user.comment_karma,
            total_posts=post_count,
            total_comments=comment_count
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving user stats: {str(e)}")

@app.get("/api/user/posts", response_model=List[PostResponse])
def get_user_posts(
    limit: int = 10,
    sort_order: str = "newest",
    reddit: praw.Reddit = Depends(get_reddit_instance)
):
    """
    Get user's posts.
    
    Args:
        limit: Number of posts to retrieve (default: 10)
        sort_order: "oldest" or "newest" (default: "newest")
    """
    if sort_order not in ["oldest", "newest"]:
        raise HTTPException(status_code=400, detail="sort_order must be 'oldest' or 'newest'")
    
    try:
        user = reddit.user.me()
        posts = []
        
        if sort_order == "oldest":
            # Get all posts and sort by creation time
            all_posts = list(user.submissions.new(limit=None))
            all_posts.sort(key=lambda x: x.created_utc)
            selected_posts = all_posts[:limit]
        else:
            # Get newest posts directly
            selected_posts = user.submissions.new(limit=limit)
        
        for post in selected_posts:
            created_time = datetime.fromtimestamp(post.created_utc)
            
            # Create content preview for text posts
            content_preview = None
            if post.selftext:
                content_preview = post.selftext[:200] + "..." if len(post.selftext) > 200 else post.selftext
            
            posts.append(PostResponse(
                title=post.title,
                subreddit=post.subreddit.display_name,
                score=post.score,
                ups=post.ups,
                downs=post.downs,
                num_comments=post.num_comments,
                created_utc=post.created_utc,
                created_time=created_time.strftime('%Y-%m-%d %H:%M:%S'),
                permalink=post.permalink,
                url=f"https://reddit.com{post.permalink}",
                selftext=post.selftext,
                content_preview=content_preview
            ))
        
        return posts
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving posts: {str(e)}")

@app.get("/api/user/comments", response_model=List[CommentResponse])
def get_user_comments(
    limit: int = 10,
    sort_order: str = "newest",
    reddit: praw.Reddit = Depends(get_reddit_instance)
):
    """
    Get user's comments.
    
    Args:
        limit: Number of comments to retrieve (default: 10)
        sort_order: "oldest" or "newest" (default: "newest")
    """
    if sort_order not in ["oldest", "newest"]:
        raise HTTPException(status_code=400, detail="sort_order must be 'oldest' or 'newest'")
    
    try:
        user = reddit.user.me()
        comments = []
        
        if sort_order == "oldest":
            # Get all comments and sort by creation time
            all_comments = list(user.comments.new(limit=None))
            all_comments.sort(key=lambda x: x.created_utc)
            selected_comments = all_comments[:limit]
        else:
            # Get newest comments directly
            selected_comments = user.comments.new(limit=limit)
        
        for comment in selected_comments:
            created_time = datetime.fromtimestamp(comment.created_utc)
            
            # Create comment preview
            comment_preview = comment.body[:200] + "..." if len(comment.body) > 200 else comment.body
            
            comments.append(CommentResponse(
                subreddit=comment.subreddit.display_name,
                post_title=comment.submission.title,
                score=comment.score,
                created_utc=comment.created_utc,
                created_time=created_time.strftime('%Y-%m-%d %H:%M:%S'),
                body=comment.body,
                comment_preview=comment_preview,
                permalink=comment.permalink,
                url=f"https://reddit.com{comment.permalink}"
            ))
        
        return comments
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving comments: {str(e)}")

@app.post("/api/user/stats/with-credentials", response_model=UserStats)
def get_user_stats_with_credentials(credentials: RedditCredentials):
    """
    Get user statistics using provided credentials.
    """
    reddit = create_reddit_instance_with_credentials(credentials)
    
    try:
        user = reddit.user.me()
        
        # Count posts and comments
        post_count = sum(1 for _ in user.submissions.new(limit=None))
        comment_count = sum(1 for _ in user.comments.new(limit=None))
        
        return UserStats(
            username=user.name,
            account_created=datetime.fromtimestamp(user.created_utc).strftime('%Y-%m-%d'),
            link_karma=user.link_karma,
            comment_karma=user.comment_karma,
            total_karma=user.link_karma + user.comment_karma,
            total_posts=post_count,
            total_comments=comment_count
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving user stats: {str(e)}")

@app.post("/api/user/posts/with-credentials", response_model=List[PostResponse])
def get_user_posts_with_credentials(
    credentials: RedditCredentials,
    limit: int = 10,
    sort_order: str = "newest"
):
    """
    Get user's posts using provided credentials.
    """
    if sort_order not in ["oldest", "newest"]:
        raise HTTPException(status_code=400, detail="sort_order must be 'oldest' or 'newest'")
    
    reddit = create_reddit_instance_with_credentials(credentials)
    
    try:
        user = reddit.user.me()
        posts = []
        
        if sort_order == "oldest":
            all_posts = list(user.submissions.new(limit=None))
            all_posts.sort(key=lambda x: x.created_utc)
            selected_posts = all_posts[:limit]
        else:
            selected_posts = user.submissions.new(limit=limit)
        
        for post in selected_posts:
            created_time = datetime.fromtimestamp(post.created_utc)
            
            content_preview = None
            if post.selftext:
                content_preview = post.selftext[:200] + "..." if len(post.selftext) > 200 else post.selftext
            
            posts.append(PostResponse(
                title=post.title,
                subreddit=post.subreddit.display_name,
                score=post.score,
                ups=post.ups,
                downs=post.downs,
                num_comments=post.num_comments,
                created_utc=post.created_utc,
                created_time=created_time.strftime('%Y-%m-%d %H:%M:%S'),
                permalink=post.permalink,
                url=f"https://reddit.com{post.permalink}",
                selftext=post.selftext,
                content_preview=content_preview
            ))
        
        return posts
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving posts: {str(e)}")

@app.post("/api/user/comments/with-credentials", response_model=List[CommentResponse])
def get_user_comments_with_credentials(
    credentials: RedditCredentials,
    limit: int = 10,
    sort_order: str = "newest"
):
    """
    Get user's comments using provided credentials.
    """
    if sort_order not in ["oldest", "newest"]:
        raise HTTPException(status_code=400, detail="sort_order must be 'oldest' or 'newest'")
    
    reddit = create_reddit_instance_with_credentials(credentials)
    
    try:
        user = reddit.user.me()
        comments = []
        
        if sort_order == "oldest":
            all_comments = list(user.comments.new(limit=None))
            all_comments.sort(key=lambda x: x.created_utc)
            selected_comments = all_comments[:limit]
        else:
            selected_comments = user.comments.new(limit=limit)
        
        for comment in selected_comments:
            created_time = datetime.fromtimestamp(comment.created_utc)
            comment_preview = comment.body[:200] + "..." if len(comment.body) > 200 else comment.body
            
            comments.append(CommentResponse(
                subreddit=comment.subreddit.display_name,
                post_title=comment.submission.title,
                score=comment.score,
                created_utc=comment.created_utc,
                created_time=created_time.strftime('%Y-%m-%d %H:%M:%S'),
                body=comment.body,
                comment_preview=comment_preview,
                permalink=comment.permalink,
                url=f"https://reddit.com{comment.permalink}"
            ))
        
        return comments
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving comments: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    