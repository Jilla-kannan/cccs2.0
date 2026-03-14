from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'student', 'complaint_staff', 'notice_staff', 'principal', 'admin'
    department = db.Column(db.String(100), nullable=True)
    year = db.Column(db.String(20), nullable=True) # e.g. 1st Year, 2nd Year
    phone = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    complaints = db.relationship('Complaint', foreign_keys='Complaint.student_id', backref='author', lazy=True)
    assigned_complaints = db.relationship('Complaint', foreign_keys='Complaint.assigned_staff', backref='assignee', lazy=True)
    notices = db.relationship('Notice', backref='poster', lazy=True)

class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=False)  # 'academic', 'hostel', 'facilities', 'other'
    priority = db.Column(db.String(20), nullable=False, default='medium') # 'low', 'medium', 'high'
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    anonymous = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), nullable=False, default='submitted')
    # status options: submitted, under_review, resolved, escalated
    assigned_staff = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    image = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    updates = db.relationship('ComplaintUpdate', backref='complaint', lazy=True, cascade="all, delete-orphan", order_by='ComplaintUpdate.timestamp')

class ComplaintUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey('complaint.id'), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    proof_file = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    updater = db.relationship('User', foreign_keys=[updated_by])

class Notice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False, default='circular') # 'alert', 'circular', 'campus_instruction', 'event'
    priority = db.Column(db.String(20), nullable=False, default='normal') # 'normal', 'important', 'urgent'
    file_attachment = db.Column(db.Text, nullable=True)
    expiry_date = db.Column(db.DateTime, nullable=True)
    posted_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
