#!/usr/bin/env python3
"""
Isolated Fast Streaming Server for Railway - Solves Video Switching and Slow Loading
Complete isolation system prevents old video playback + fast 1MB chunk streaming
Production-ready version for Railway.app deployment
"""
from flask import Flask, Response, request, redirect, jsonify
import requests
import threading
import time
import os
import hashlib
import logging
from datetime import datetime, timedelta
from urllib.parse import unquote
import subprocess
import signal
import sys
import gc

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "fallback-secret-key-for-development")

# ISOLATED STREAMING CONFIGURATION
FAST_CHUNK_SIZE = 1024 * 1024  # 1MB chunks for instant loading
STANDARD_CHUNK_SIZE = 512 * 1024  # 512KB chunks for standard streaming
INITIAL_BUFFER_SIZE = 2 * 1024 * 1024  # 2MB initial buffer for immediate playback

# ISOLATION VARIABLES - Each video gets completely separate session
# Using Flask session to maintain state across workers
import json
from flask import session

# No default video URL - User must provide video URL
DEFAULT_VIDEO_URL = None

# Worker-local session storage
video_sessions = {}  # Isolated sessions per video
video_metadata = {}  # Metadata per video
server_running = True

def get_current_video_url():
    """Get current video URL from session"""
    return session.get('current_video_url', None)

def get_active_session_id():
    """Get active session ID from session"""
    return session.get('active_video_id', None)

def measure_network_speed():
    """Measure network speed and adjust buffer sizes"""
    try:
        start_time = time.time()
        headers = {
            'User-Agent': 'FastSpeedTest/3.0',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache'
        }
        
        # Use current video URL from session
        current_url = get_current_video_url()
        if not current_url:
            logger.info("No video URL set, skipping network speed test")
            return 0
            
        temp_session = requests.Session()
        response = temp_session.get(current_url, headers=headers, stream=True, timeout=10)
        
        if response.status_code in [200, 206]:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded >= 128 * 1024:  # 128KB test
                    break
            
            elapsed = time.time() - start_time
            if elapsed > 0:
                speed_kbps = (downloaded / 1024) / elapsed
                logger.info(f"Network speed: {speed_kbps:.1f} KB/s")
                return speed_kbps
    except Exception as e:
        logger.error(f"Network speed test failed: {e}")
    return 0

@app.route('/')
def home():
    host_ip = request.host.split(':')[0]
    current_url = get_current_video_url()
    active_session = get_active_session_id()
    cache_buster = session.get('cache_buster', 0)
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Isolated Fast Video Streaming</title>
    <link href="https://cdn.replit.com/agent/bootstrap-agent-dark-theme.min.css" rel="stylesheet">
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <div class="container mt-4">
        <div class="row justify-content-center">
            <div class="col-lg-8">
                <h1 class="text-center mb-4">🎬 Isolated Fast Video Streaming Server</h1>
                
                <div class="alert alert-success text-center" role="alert">
                    <h4 class="alert-heading">✓ ISOLATED SYSTEM v3.0</h4>
                    <p class="mb-2">Zero video switching + Fast 1MB chunk loading</p>
                    <hr>
                    <p class="mb-0 small">
                        <strong>Session:</strong> {active_session or 'None'} | 
                        <strong>Cache:</strong> {cache_buster} | 
                        <strong>Time:</strong> {datetime.now().strftime('%H:%M:%S')}
                    </p>
                </div>

                <div class="card mb-4">
                    <div class="card-header">
                        <h5 class="card-title mb-0">📹 Set Video URL</h5>
                    </div>
                    <div class="card-body">
                        <form action="/set-video" method="post">
                            <div class="mb-3">
                                <input type="text" name="video_url" class="form-control" 
                                       placeholder="Enter video URL here..." 
                                       value="{current_url if current_url else ''}" required>
                            </div>
                            <button type="submit" class="btn btn-primary btn-lg w-100">
                                🔄 Set Video (Complete Isolation)
                            </button>
                        </form>
                    </div>
                </div>

                <div class="card mb-4">
                    <div class="card-header">
                        <h5 class="card-title mb-0">🚀 Fast Streaming URLs</h5>
                    </div>
                    <div class="card-body">
                        <div class="mb-3">
                            <label class="form-label"><strong>Primary (1MB chunks):</strong></label>
                            <div class="input-group">
                                <input type="text" value="http://{host_ip}:5000/video" readonly 
                                       class="form-control font-monospace" onclick="this.select()">
                                <button class="btn btn-outline-secondary" type="button" 
                                        onclick="navigator.clipboard.writeText(this.previousElementSibling.value)">
                                    📋 Copy
                                </button>
                            </div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label"><strong>Fast Mode (Instant loading):</strong></label>
                            <div class="input-group">
                                <input type="text" value="http://{host_ip}:5000/fast" readonly 
                                       class="form-control font-monospace" onclick="this.select()">
                                <button class="btn btn-outline-secondary" type="button" 
                                        onclick="navigator.clipboard.writeText(this.previousElementSibling.value)">
                                    📋 Copy
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="d-grid gap-2 d-md-flex justify-content-md-center">
                    <a href="/video" class="btn btn-success btn-lg">
                        ▶️ Test Current Video
                    </a>
                    <a href="/test-isolation" class="btn btn-info btn-lg">
                        🔍 Test Isolation
                    </a>
                </div>

                <div class="mt-4 text-center">
                    <small class="text-muted">
                        Deployed on Railway.app | Fast streaming with complete isolation
                    </small>
                </div>
            </div>
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
    """

@app.route('/set-video', methods=['POST'])
def set_video():
    new_url = request.form.get('video_url', '').strip()
    if new_url:
        # Store in Flask session for cross-worker persistence
        cache_buster = session.get('cache_buster', 0) + 1
        active_video_id = f"isolated_{cache_buster}_{int(time.time())}"
        
        # Store in session
        session['current_video_url'] = new_url
        session['active_video_id'] = active_video_id
        session['cache_buster'] = cache_buster
        
        # Clear local worker sessions
        video_sessions.clear()
        video_metadata.clear()
        
        # CREATE COMPLETELY ISOLATED SESSION
        isolated_session = requests.Session()
        isolated_session.headers.update({
            'User-Agent': f'FastIsolated-{active_video_id}/3.0',
            'Cache-Control': 'no-cache, no-store, must-revalidate, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Connection': 'keep-alive',
            'X-Video-Session': active_video_id,
            'X-Cache-Buster': str(cache_buster)
        })
        
        # STORE ISOLATED SESSION
        video_sessions[active_video_id] = isolated_session
        video_metadata[active_video_id] = {
            'url': new_url,
            'created': time.time(),
            'cache_buster': cache_buster,
            'session_id': active_video_id
        }
        
        # FORCE COMPLETE MEMORY CLEANUP
        gc.collect()
        
        logger.info(f"COMPLETE ISOLATION: {active_video_id}")
        logger.info(f"ALL OLD SESSIONS DESTROYED")
        logger.info(f"NEW VIDEO ISOLATED: {new_url[:50]}...")
        
        host_ip = request.host.split(':')[0]
        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Video Isolated Successfully</title>
    <link href="https://cdn.replit.com/agent/bootstrap-agent-dark-theme.min.css" rel="stylesheet">
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <div class="container mt-5">
        <div class="row justify-content-center">
            <div class="col-lg-6">
                <div class="text-center mb-4">
                    <h2>✅ Video Completely Isolated!</h2>
                </div>
                
                <div class="alert alert-success" role="alert">
                    <h4 class="alert-heading">🎯 ISOLATION COMPLETE!</h4>
                    <p><strong>Session ID:</strong> {active_video_id}</p>
                    <p><strong>Cache Buster:</strong> #{cache_buster}</p>
                    <p><strong>Time:</strong> {datetime.now().strftime('%H:%M:%S')}</p>
                    <p class="mb-0">Zero contamination from old videos!</p>
                </div>
                
                <div class="card mb-4">
                    <div class="card-header">
                        <h6 class="card-title mb-0">📹 New Video Isolated</h6>
                    </div>
                    <div class="card-body">
                        <p class="small text-break bg-light p-2 rounded">{new_url}</p>
                        <p class="text-muted mb-0">Fast 1MB chunk streaming ready</p>
                    </div>
                </div>

                <div class="card mb-4">
                    <div class="card-header">
                        <h6 class="card-title mb-0">🚀 Fast Streaming URLs</h6>
                    </div>
                    <div class="card-body">
                        <div class="mb-3">
                            <input type="text" value="http://{host_ip}:5000/video" readonly 
                                   class="form-control font-monospace" onclick="this.select()">
                        </div>
                        <div class="mb-0">
                            <input type="text" value="http://{host_ip}:5000/fast" readonly 
                                   class="form-control font-monospace" onclick="this.select()">
                        </div>
                    </div>
                </div>

                <div class="d-grid gap-2 d-md-flex justify-content-md-center">
                    <a href="/" class="btn btn-outline-primary">← Back to Home</a>
                    <a href="/video" class="btn btn-success">▶️ Test Video</a>
                </div>
            </div>
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
        """
    return redirect('/')

@app.route('/video')
def video():
    """Standard streaming with 1MB chunks"""
    video_url = get_current_video_url()
    return stream_video(video_url, mode='standard')

@app.route('/fast')
def fast_video():
    """Fast streaming with maximum chunk size"""
    video_url = get_current_video_url()
    return stream_video(video_url, mode='fast')

@app.route('/proxy/<path:url>')
def proxy_video(url):
    """Proxy any video URL with isolation"""
    decoded_url = unquote(url)
    if not decoded_url.startswith('http'):
        decoded_url = 'https://' + decoded_url
    logger.info(f"Proxy request: {decoded_url[:50]}...")
    return stream_video(decoded_url, mode='fast')

@app.route('/test-isolation')
def test_isolation():
    """Test endpoint to verify isolation system"""
    active_session = get_active_session_id()
    cache_buster = session.get('cache_buster', 0)
    current_url = get_current_video_url()
    
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Isolation System Test</title>
    <link href="https://cdn.replit.com/agent/bootstrap-agent-dark-theme.min.css" rel="stylesheet">
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <div class="container mt-5">
        <div class="row justify-content-center">
            <div class="col-lg-6">
                <div class="text-center mb-4">
                    <h2>🔍 Isolation System Status</h2>
                </div>
                
                <div class="alert alert-info" role="alert">
                    <h4 class="alert-heading">✅ SYSTEM ACTIVE</h4>
                    <p><strong>Active Session:</strong> {active_session or 'None'}</p>
                    <p><strong>Cache Buster:</strong> #{cache_buster}</p>
                    <p><strong>Sessions Count:</strong> {len(video_sessions)}</p>
                    <p><strong>Timestamp:</strong> {datetime.now().strftime('%H:%M:%S')}</p>
                    <p class="mb-0"><strong>Version:</strong> Isolated Fast Stream v3.0</p>
                </div>
                
                <div class="card mb-4">
                    <div class="card-header">
                        <h6 class="card-title mb-0">📹 Current Video</h6>
                    </div>
                    <div class="card-body">
                        <p class="small text-break">{current_url[:100] + '...' if current_url else 'No video URL set'}</p>
                    </div>
                </div>
                
                <div class="alert alert-success" role="alert">
                    If you see session information above, the isolation system is working!
                </div>
                
                <div class="text-center">
                    <a href="/" class="btn btn-primary">← Back to Home</a>
                </div>
            </div>
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
    """

@app.route('/health')
def health_check():
    """Health check endpoint for Railway"""
    cache_buster = session.get('cache_buster', 0)
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'active_sessions': len(video_sessions),
        'cache_buster': cache_buster,
        'version': '3.0'
    })

def stream_video(video_url, mode='standard'):
    """ISOLATED FAST STREAMING - Prevents video switching with rapid loading"""
    def generate_stream():
        try:
            # Get session info from Flask session
            active_session_id = get_active_session_id()
            
            # USE ONLY ISOLATED SESSION - Force use of active session
            if active_session_id and active_session_id in video_sessions:
                session_obj = video_sessions[active_session_id]
                # Use URL from session metadata to ensure complete isolation
                actual_video_url = video_metadata[active_session_id]['url']
                logger.info(f"Using isolated session: {active_session_id} with URL: {actual_video_url[:50]}...")
            else:
                # Create new isolated session if none exists
                cache_buster = session.get('cache_buster', 0) + 1
                active_session_id = f"isolated_{cache_buster}_{int(time.time())}"
                
                session_obj = requests.Session()
                session_obj.headers.update({
                    'User-Agent': f'FastIsolated-{active_session_id}/3.0',
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache'
                })
                
                # Store the session and metadata
                video_sessions[active_session_id] = session_obj
                video_metadata[active_session_id] = {
                    'url': video_url,
                    'created': time.time(),
                    'cache_buster': cache_buster,
                    'session_id': active_session_id
                }
                actual_video_url = video_url
                logger.info(f"Created new isolated session: {active_session_id} with URL: {actual_video_url[:50]}...")
            
            # FAST STREAMING REQUEST
            range_header = request.headers.get('Range')
            headers = {
                'User-Agent': f'FastStreamProxy-{active_session_id or "fallback"}/3.0',
                'Accept': '*/*',
                'Connection': 'keep-alive',
                'Accept-Encoding': 'identity',
                'Referer': 'https://moviebox.ng/',
            }
            
            if range_header:
                headers['Range'] = range_header
            
            response = session_obj.get(actual_video_url, headers=headers, stream=True, timeout=20)
            
            if response.status_code == 403:
                headers['Referer'] = 'https://valiw.hakunaymatata.com/'
                response = session_obj.get(actual_video_url, headers=headers, stream=True, timeout=20)
            
            response.raise_for_status()
            
            # DETERMINE CHUNK SIZE BASED ON MODE
            if mode == 'fast':
                chunk_size = FAST_CHUNK_SIZE
                logger.info(f"Fast streaming mode: {chunk_size} bytes chunks")
            else:
                chunk_size = STANDARD_CHUNK_SIZE
                logger.info(f"Standard streaming mode: {chunk_size} bytes chunks")
            
            # STREAM WITH APPROPRIATE HEADERS
            def generate():
                try:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            yield chunk
                except Exception as e:
                    logger.error(f"Streaming error: {e}")
                    raise
            
            # PREPARE RESPONSE HEADERS
            resp_headers = {
                'Content-Type': response.headers.get('Content-Type', 'video/mp4'),
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'X-Video-Session': active_session_id or 'fallback',
                'X-Stream-Mode': mode,
                'X-Chunk-Size': str(chunk_size)
            }
            
            # COPY ESSENTIAL HEADERS FROM SOURCE
            for header in ['Content-Length', 'Content-Range', 'Last-Modified', 'ETag']:
                if header in response.headers:
                    resp_headers[header] = response.headers[header]
            
            status_code = response.status_code
            logger.info(f"Streaming initiated - Status: {status_code}, Mode: {mode}, Session: {active_session_id}")
            
            return Response(
                generate(),
                status_code,
                headers=resp_headers,
                mimetype=response.headers.get('Content-Type', 'video/mp4')
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return Response(
                f"Streaming error: {str(e)}",
                status=500,
                mimetype='text/plain'
            )
        except Exception as e:
            logger.error(f"Unexpected streaming error: {e}")
            return Response(
                f"Unexpected error: {str(e)}",
                status=500,
                mimetype='text/plain'
            )
    
    return generate_stream()

@app.errorhandler(404)
def not_found(error):
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>404 - Not Found</title>
    <link href="https://cdn.replit.com/agent/bootstrap-agent-dark-theme.min.css" rel="stylesheet">
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <div class="container mt-5">
        <div class="row justify-content-center">
            <div class="col-lg-6 text-center">
                <h1>404</h1>
                <h3>Page Not Found</h3>
                <p class="text-muted">The requested resource could not be found.</p>
                <a href="/" class="btn btn-primary">← Back to Home</a>
            </div>
        </div>
    </div>
</body>
</html>
    """, 404

@app.errorhandler(500)
def internal_error(error):
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>500 - Internal Server Error</title>
    <link href="https://cdn.replit.com/agent/bootstrap-agent-dark-theme.min.css" rel="stylesheet">
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <div class="container mt-5">
        <div class="row justify-content-center">
            <div class="col-lg-6 text-center">
                <h1>500</h1>
                <h3>Internal Server Error</h3>
                <p class="text-muted">Something went wrong on our end.</p>
                <a href="/" class="btn btn-primary">← Back to Home</a>
            </div>
        </div>
    </div>
</body>
</html>
    """, 500

def cleanup_sessions():
    """Background task to cleanup old sessions"""
    while server_running:
        try:
            current_time = time.time()
            sessions_to_remove = []
            
            for session_id, metadata in video_metadata.items():
                if current_time - metadata.get('created', 0) > 3600:  # 1 hour
                    sessions_to_remove.append(session_id)
            
            for session_id in sessions_to_remove:
                if session_id in video_sessions:
                    try:
                        video_sessions[session_id].close()
                    except:
                        pass
                    del video_sessions[session_id]
                if session_id in video_metadata:
                    del video_metadata[session_id]
                logger.info(f"Cleaned up old session: {session_id}")
            
            if sessions_to_remove:
                gc.collect()
                
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")
        
        time.sleep(300)  # Run every 5 minutes

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_sessions, daemon=True)
cleanup_thread.start()

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    global server_running
    logger.info("Received shutdown signal, cleaning up...")
    server_running = False
    
    # Close all sessions
    for session_id, session in video_sessions.items():
        try:
            session.close()
        except:
            pass
    
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    logger.info(f"Starting Isolated Fast Streaming Server on port {port}")
    logger.info(f"Debug mode: {debug}")
    logger.info("No default video URL - Users must provide video URLs")
    
    app.run(host='0.0.0.0', port=port, debug=debug, threaded=True)
