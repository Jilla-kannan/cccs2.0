import os
import secrets
import csv
from io import StringIO, BytesIO
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request, abort, make_response, send_file, send_from_directory

from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from models import db, User, Complaint, ComplaintUpdate, Notice
from werkzeug.utils import secure_filename

# Expensive imports moved inside routes to speed up cold starts
# from fpdf import FPDF


ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Detect if running on Vercel
IS_VERCEL = "VERCEL" in os.environ

def save_upload(file_obj, upload_folder):
    """Save an uploaded file and return its stored filename, or None."""
    if not file_obj or file_obj.filename == '':
        return None
    if allowed_file(file_obj.filename):
        ext = file_obj.filename.rsplit('.', 1)[1].lower()
        unique_name = f"{secrets.token_hex(8)}.{ext}"
        file_obj.save(os.path.join(upload_folder, unique_name))
        return unique_name
    return None


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'cccs_secret_key_2024'
    if IS_VERCEL:
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/site.db'
        app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
        app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
    
    # Ensure upload folder exists
    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create upload folder {app.config['UPLOAD_FOLDER']}: {e}")

    db.init_app(app)
    bcrypt = Bcrypt(app)

    login_manager = LoginManager(app)
    login_manager.login_view = 'login'
    login_manager.login_message_category = 'warning'
    login_manager.login_message = 'Please log in to access this page.'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ------------------------------------------------------------------ #
    #  Database seeding – create predefined users on first run             #
    # ------------------------------------------------------------------ #
    with app.app_context():
        # db.drop_all() # Commented out to prevent data loss on every restart
        db.create_all()
        # Optimize seeding: check if any users exist first

        if User.query.first() is None:
            staff_data = [
                ('JD', 'jd@cccs.edu', 'jd@123', 'complaint_staff', 'Maintenance'),
                ('RK', 'rk@cccs.edu', 'rk@123', 'complaint_staff', 'Facilities'),
                ('SK', 'sk@cccs.edu', 'sk@123', 'complaint_staff', 'Academic Affairs'),
                ('JK', 'jk@cccs.edu', 'jk@123', 'notice_staff', 'Administration'),
                ('Keerthu (Principal)', 'keerthu@cccs.edu', 'k@123', 'principal', 'Administration'),
                ('Admin', 'admin@cccs.edu', 'admin@123', 'admin', 'Management')
            ]

            for name, email, password, role, dept in staff_data:
                hashed = bcrypt.generate_password_hash(password, 10).decode('utf-8')
                user = User(name=name, email=email, password=hashed, role=role, department=dept)
                db.session.add(user)
            db.session.commit()


    # ================================================================== #
    #  COMMON ROUTES                                                       #
    # ================================================================== #

    @app.route('/')
    def home():
        if current_user.is_authenticated:
            return _redirect_by_role()
        
        total_complaints = Complaint.query.count()
        resolved_complaints = Complaint.query.filter_by(status='resolved').count()
        recent_notices = Notice.query.order_by(Notice.date.desc()).limit(3).all()
        recent_complaints = Complaint.query.order_by(Complaint.created_at.desc()).limit(2).all()
        
        return render_template('home.html', 
                               total_count=total_complaints,
                               resolved_count=resolved_complaints,
                               notices=recent_notices,
                               complaints=recent_complaints)

    def _redirect_by_role():
        if current_user.role == 'student':
            return redirect(url_for('student_dashboard'))
        elif current_user.role == 'complaint_staff':
            return redirect(url_for('staff_dashboard'))
        elif current_user.role == 'notice_staff':
            return redirect(url_for('notice_staff_dashboard'))
        elif current_user.role == 'principal':
            return redirect(url_for('principal_dashboard'))
        elif current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))

    @app.route('/uploads/<filename>')
    def uploaded_file(filename):
        # 1. Try configured UPLOAD_FOLDER (usually /tmp on Vercel)
        if os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], filename)):
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
        
        # 2. Try static/uploads (fallback for deployed files)
        static_uploads = os.path.join(app.root_path, 'static', 'uploads')
        if os.path.exists(os.path.join(static_uploads, filename)):
            return send_from_directory(static_uploads, filename)
            
        # 3. Last resort fallback
        return abort(404)


    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return _redirect_by_role()
        if request.method == 'POST':
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '')
            user = User.query.filter_by(email=email).first()
            if user and bcrypt.check_password_hash(user.password, password):
                login_user(user, remember=bool(request.form.get('remember')))
                return _redirect_by_role()
            flash('Invalid email or password. Please try again.', 'danger')
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        from flask import session
        logout_user()
        session.clear() # Completely clear the session
        flash('You have been logged out.', 'info')
        return redirect(url_for('home'))


    @app.route('/notices')
    @login_required
    def view_all_notices():
        notices = Notice.query.order_by(Notice.date.desc()).all()
        return render_template('notices.html', notices=notices)

    @app.route('/students')
    @login_required
    def view_all_students():
        if current_user.role not in ['principal', 'notice_staff', 'complaint_staff', 'admin']:
            abort(403)
        
        dept_filter = request.args.get('department', '')
        if dept_filter:
            students = User.query.filter_by(role='student', department=dept_filter).all()
        else:
            students = User.query.filter_by(role='student').all()
            
        departments = db.session.query(User.department).filter(User.role == 'student').distinct().all()
        departments = [d[0] for d in departments if d[0]]
        
        return render_template('staff/all_students.html', 
                               students=students, 
                               departments=departments,
                               selected_dept=dept_filter)

    @app.after_request
    def add_header(response):
        """
        Add headers to both force latest IE rendering engine or lately Edge,
        and also to cache the rendered page for 0 seconds.
        """
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    @app.route('/register', methods=['GET', 'POST'])

    def register():
        if current_user.is_authenticated:
            return _redirect_by_role()
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            department = request.form.get('department', '').strip()
            year = request.form.get('year', '').strip()
            phone = request.form.get('phone', '').strip()

            if not name or not email or not password or not department:
                flash('Required fields are missing.', 'danger')
            elif password != confirm_password:
                flash('Passwords do not match.', 'danger')
            elif User.query.filter_by(email=email).first():
                flash('Email already registered.', 'danger')
            else:
                hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
                user = User(name=name, email=email, password=hashed_password, role='student', 
                            department=department, year=year, phone=phone)
                db.session.add(user)
                db.session.commit()
                flash('Your account has been created! You can now log in.', 'success')
                return redirect(url_for('login'))
        return render_template('register.html')

    # ================================================================== #
    #  STUDENT ROUTES                                                      #
    # ================================================================== #

    @app.route('/student/dashboard')
    @login_required
    def student_dashboard():
        if current_user.role != 'student':
            abort(403)
        complaints = (Complaint.query
                      .filter_by(student_id=current_user.id)
                      .order_by(Complaint.created_at.desc())
                      .all())
        notices = Notice.query.order_by(Notice.date.desc()).limit(5).all()
        return render_template('student/dashboard.html',
                               complaints=complaints, notices=notices)

    @app.route('/student/all_complaints')
    @login_required
    def student_all_complaints():
        if current_user.role != 'student':
            abort(403)
        # Only show non-anonymous complaints or just basic details
        all_comp = Complaint.query.order_by(Complaint.created_at.desc()).all()
        return render_template('student/all_complaints.html', complaints=all_comp)

    @app.route('/student/submit', methods=['GET', 'POST'])
    @login_required
    def submit_complaint():
        if current_user.role != 'student':
            abort(403)
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            category = request.form.get('category', '').strip()
            manual_category = request.form.get('manual_category', '').strip()
            priority = request.form.get('priority', 'medium')
            description = request.form.get('description', '').strip()
            anonymous = bool(request.form.get('anonymous'))

            if category == 'Other' and manual_category:
                category = manual_category

            if not title or not category or not description:
                flash('Please fill in all required fields.', 'danger')
                return render_template('student/submit_complaint.html')

            # Save attachment
            image_file = request.files.get('image')
            stored_name = save_upload(image_file, app.config['UPLOAD_FOLDER'])

            complaint_id_str = f"CMP{secrets.randbelow(90000) + 10000}"
            
            # Simple auto-assignment logic: rotate among complaint staff
            comp_staff = User.query.filter_by(role='complaint_staff').all()
            assigned_id = None
            if comp_staff:
                # Pick one (could be based on load, but here just random/first for now)
                assigned_id = comp_staff[secrets.randbelow(len(comp_staff))].id

            complaint = Complaint(
                complaint_id=complaint_id_str,
                title=title,
                category=category,
                priority=priority,
                description=description,
                student_id=current_user.id,
                anonymous=anonymous,
                image=stored_name,
                status='submitted',
                assigned_staff=assigned_id
            )
            db.session.add(complaint)
            db.session.commit()
            flash(f'Complaint submitted successfully! Your ID is <strong>{complaint_id_str}</strong>.', 'success')
            return redirect(url_for('student_dashboard'))

        return render_template('student/submit_complaint.html')

    @app.route('/student/complaint/<int:complaint_id>')
    @login_required
    def view_complaint(complaint_id):
        complaint = Complaint.query.get_or_404(complaint_id)
        # Students can only view their own complaints
        if current_user.role == 'student' and complaint.student_id != current_user.id:
            abort(403)
        return render_template('student/view_complaint.html', complaint=complaint)

    # ================================================================== #
    #  STAFF ROUTES                                                        #
    # ================================================================== #

    @app.route('/staff/dashboard')
    @login_required
    def staff_dashboard():
        if current_user.role != 'complaint_staff':
            abort(403)
        # REQUIREMENT: All staff can view complaints from all categories.
        all_complaints = (Complaint.query
                    .order_by(Complaint.updated_at.desc())
                    .all())
        total = len(all_complaints)
        in_progress = sum(1 for c in all_complaints if c.status == 'under_review')
        resolved = sum(1 for c in all_complaints if c.status == 'resolved')
        # Pending covers both 'submitted' (auto-assigned) and 'assigned' (principal assigned)
        pending = sum(1 for c in all_complaints if c.status in ['submitted', 'assigned'])
        return render_template('staff/dashboard.html',
                               complaints=all_complaints,
                               total=total,
                               in_progress=in_progress,
                               resolved=resolved,
                               pending=pending)

    @app.route('/staff/complaint/<int:complaint_id>', methods=['GET', 'POST'])
    @login_required
    def staff_update_complaint(complaint_id):
        if current_user.role != 'complaint_staff':
            abort(403)
        complaint = Complaint.query.get_or_404(complaint_id)
        # REQUIREMENT: Any of the three staff members should be able to resolve complaints.
        # (Assignment check removed)

        if request.method == 'POST':
            message = request.form.get('message', '').strip()
            new_status = request.form.get('status', complaint.status)

            if not message:
                flash('Update message cannot be empty.', 'danger')
            else:
                # Save proof file
                proof = request.files.get('proof_file')
                proof_stored = save_upload(proof, app.config['UPLOAD_FOLDER'])

                update = ComplaintUpdate(
                    complaint_id=complaint.id,
                    updated_by=current_user.id,
                    message=message,
                    status=new_status,
                    proof_file=proof_stored
                )
                complaint.status = new_status
                complaint.updated_at = datetime.utcnow()
                db.session.add(update)
                db.session.commit()
                flash('Complaint updated successfully.', 'success')
                return redirect(url_for('staff_update_complaint', complaint_id=complaint_id))

        return render_template('staff/complaint_detail.html', complaint=complaint)

    # ================================================================== #
    #  NOTICE STAFF ROUTES                                                   #
    # ================================================================== #

    @app.route('/notice_staff/dashboard')
    @login_required
    def notice_staff_dashboard():
        if current_user.role != 'notice_staff':
            abort(403)
        notices = Notice.query.order_by(Notice.date.desc()).all()
        students = User.query.filter_by(role='student').all()
        return render_template('notice_staff/dashboard.html', notices=notices, students=students)

    @app.route('/notice_staff/post', methods=['POST'])
    @login_required
    def notice_staff_post_notice():
        if current_user.role not in ['notice_staff', 'principal']:
            abort(403)
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        category = request.form.get('category', 'circular')
        priority = request.form.get('priority', 'normal')
        
        if not title or not message:
            flash('Title and message are required.', 'danger')
        else:
            attachment = request.files.get('attachment')
            stored_name = save_upload(attachment, app.config['UPLOAD_FOLDER'])
            
            notice = Notice(title=title, message=message, category=category, 
                            priority=priority, file_attachment=stored_name, posted_by=current_user.id)
            db.session.add(notice)
            db.session.commit()
            flash('Notice posted successfully.', 'success')
        
        if current_user.role == 'principal':
            return redirect(url_for('principal_dashboard'))
        return redirect(url_for('notice_staff_dashboard'))

    # ================================================================== #
    #  PRINCIPAL ROUTES                                                    #
    # ================================================================== #

    @app.route('/principal/dashboard')
    @login_required
    def principal_dashboard():
        if current_user.role != 'principal':
            abort(403)
        all_complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
        # Include both complaint and notice staff for assignment flexibility
        staff_list = User.query.filter(User.role.in_(['complaint_staff', 'notice_staff'])).all()
        notices = Notice.query.order_by(Notice.date.desc()).all()

        total = len(all_complaints)
        pending = sum(1 for c in all_complaints if c.status == 'submitted')
        escalated = sum(1 for c in all_complaints if c.status == 'escalated')
        resolved = sum(1 for c in all_complaints if c.status == 'resolved')
        student_count = User.query.filter_by(role='student').count()

        # Analytics Data
        categories = ['academic', 'hostel', 'facilities', 'other']
        cat_counts = [sum(1 for c in all_complaints if c.category.lower() == cat) for cat in categories]
        
        statuses = ['submitted', 'under_review', 'resolved', 'escalated']
        status_counts = [sum(1 for c in all_complaints if c.status == s) for s in statuses]

        return render_template('principal/dashboard.html',
                               complaints=all_complaints,
                               staff_list=staff_list,
                               notices=notices,
                               total=total,
                               pending=pending,
                               escalated=escalated,
                               resolved=resolved,
                               student_count=student_count)

    @app.route('/principal/assign/<int:complaint_id>', methods=['POST'])
    @login_required
    def assign_complaint(complaint_id):
        if current_user.role != 'principal':
            abort(403)
        complaint = Complaint.query.get_or_404(complaint_id)
        staff_id = request.form.get('staff_id')
        if not staff_id:
            flash('Please select a staff member.', 'danger')
            return redirect(url_for('principal_dashboard'))
        complaint.assigned_staff = int(staff_id)
        complaint.status = 'assigned'
        complaint.updated_at = datetime.utcnow()

        update = ComplaintUpdate(
            complaint_id=complaint.id,
            updated_by=current_user.id,
            message='Complaint assigned to staff by Principal.',
            status='assigned'
        )
        db.session.add(update)
        db.session.commit()
        flash('Complaint assigned successfully.', 'success')
        return redirect(url_for('principal_dashboard'))

    @app.route('/principal/escalate/<int:complaint_id>', methods=['POST'])
    @login_required
    def escalate_complaint(complaint_id):
        if current_user.role != 'principal':
            abort(403)
        complaint = Complaint.query.get_or_404(complaint_id)
        complaint.status = 'escalated'
        complaint.updated_at = datetime.utcnow()

        update = ComplaintUpdate(
            complaint_id=complaint.id,
            updated_by=current_user.id,
            message='Complaint escalated by Principal.',
            status='escalated'
        )
        db.session.add(update)
        db.session.commit()
        flash('Complaint has been escalated.', 'warning')
        return redirect(url_for('principal_dashboard'))

    @app.route('/principal/notice', methods=['POST'])
    @login_required
    def post_notice():
        if current_user.role != 'principal':
            abort(403)
        title = request.form.get('notice_title', '').strip()
        message = request.form.get('notice_message', '').strip()
        category = request.form.get('notice_category', 'circular')
        priority = request.form.get('notice_priority', 'normal')

        if not title or not message:
            flash('Notice title and message are required.', 'danger')
        else:
            attachment = request.files.get('notice_attachment')
            stored_name = save_upload(attachment, app.config['UPLOAD_FOLDER'])
            
            notice = Notice(title=title, message=message, category=category, 
                            priority=priority, file_attachment=stored_name, posted_by=current_user.id)
            db.session.add(notice)
            db.session.commit()
            flash('Notice posted successfully.', 'success')
        return redirect(url_for('principal_dashboard'))
    
    @app.route('/principal/complaint/delete/<int:complaint_id>', methods=['POST'])
    @login_required
    def delete_complaint(complaint_id):
        if current_user.role != 'principal':
            abort(403)
        complaint = Complaint.query.get_or_404(complaint_id)
        db.session.delete(complaint)
        db.session.commit()
        flash('Complaint deleted successfully.', 'success')
        return redirect(url_for('principal_dashboard'))

    @app.route('/principal/notice/delete/<int:notice_id>', methods=['POST'])
    @login_required
    def delete_notice(notice_id):
        if current_user.role not in ['notice_staff', 'principal']:
            abort(403)
        notice = Notice.query.get_or_404(notice_id)
        db.session.delete(notice)
        db.session.commit()
        flash('Notice deleted successfully.', 'success')
        if current_user.role == 'principal':
            return redirect(url_for('principal_dashboard'))
        return redirect(url_for('notice_staff_dashboard'))

    @app.route('/principal/complaint/<int:complaint_id>')
    @login_required
    def principal_view_complaint(complaint_id):
        if current_user.role != 'principal':
            abort(403)
        complaint = Complaint.query.get_or_404(complaint_id)
        staff_list = User.query.filter(User.role.in_(['complaint_staff', 'notice_staff'])).all()
        return render_template('principal/complaint_detail.html',
                               complaint=complaint, staff_list=staff_list)

    @app.route('/principal/complaint/update/<int:complaint_id>', methods=['POST'])
    @login_required
    def principal_update_complaint(complaint_id):
        if current_user.role != 'principal':
            abort(403)
        complaint = Complaint.query.get_or_404(complaint_id)
        
        message = request.form.get('message', '').strip()
        new_status = request.form.get('status', complaint.status)

        if not message:
            flash('Response message cannot be empty.', 'danger')
        else:
            proof = request.files.get('proof_file')
            proof_stored = save_upload(proof, app.config['UPLOAD_FOLDER'])

            update = ComplaintUpdate(
                complaint_id=complaint.id,
                updated_by=current_user.id,
                message=message,
                status=new_status,
                proof_file=proof_stored
            )
            complaint.status = new_status
            complaint.updated_at = datetime.utcnow()
            db.session.add(update)
            db.session.commit()
            flash('Complaint status updated by Principal.', 'success')
            
        return redirect(url_for('principal_view_complaint', complaint_id=complaint_id))

    @app.route('/principal/analytics')
    @login_required
    def principal_analytics():
        if current_user.role != 'principal':
            abort(403)
        all_complaints = Complaint.query.all()
        
        # Analytics Data
        categories = ['academic', 'hostel', 'facilities', 'other']
        cat_counts = [sum(1 for c in all_complaints if c.category.lower() == cat) for cat in categories]
        
        statuses = ['submitted', 'under_review', 'resolved', 'escalated']
        status_counts = [sum(1 for c in all_complaints if c.status == s) for s in statuses]
        
        return render_template('principal/analytics.html',
                               cat_labels=categories,
                               cat_data=cat_counts,
                               status_labels=statuses,
                               status_data=status_counts)

    @app.route('/principal/export/csv')
    @login_required
    def export_complaints_csv():
        if current_user.role != 'principal':
            abort(403)
        complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
        si = StringIO()
        cw = csv.writer(si)
        cw.writerow(['Complaint ID', 'Title', 'Category', 'Priority', 'Status', 'Student Name', 'Date Submitted'])
        for c in complaints:
            name = c.author.name if c.author else 'Unknown'
            if c.anonymous: name = 'Anonymous'
            cw.writerow([c.complaint_id, c.title, c.category, c.priority, c.status, name, c.created_at.strftime('%Y-%m-%d %H:%M')])
        
        response = make_response(si.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=complaints_export.csv"
        response.headers["Content-Type"] = "text/csv"
        return response

    @app.route('/principal/export/pdf')
    @login_required
    def export_complaints_pdf():
        if current_user.role != 'principal':
            abort(403)
        from fpdf import FPDF
        complaints = Complaint.query.order_by(Complaint.created_at.desc()).all()
        
        pdf = FPDF()

        pdf.add_page()
        pdf.set_font("helvetica", "B", 16)
        pdf.cell(0, 10, "CCCS - Complaints Report", 0, 1, 'C')
        pdf.set_font("helvetica", "", 10)
        pdf.cell(0, 10, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 0, 1, 'C')
        pdf.ln(10)
        
        # Table Header
        pdf.set_font("helvetica", "B", 10)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(25, 10, "ID", 1, 0, 'C', 1)
        pdf.cell(65, 10, "Title", 1, 0, 'C', 1)
        pdf.cell(30, 10, "Category", 1, 0, 'C', 1)
        pdf.cell(30, 10, "Status", 1, 0, 'C', 1)
        pdf.cell(40, 10, "Student", 1, 1, 'C', 1)
        
        pdf.set_font("helvetica", "", 9)
        for c in complaints:
            name = c.author.name if c.author else 'Unknown'
            if c.anonymous: name = 'Anonymous'
            
            # Sanitize strings to avoid Unicode errors with core fonts
            safe_title = c.title.encode('latin-1', 'replace').decode('latin-1')
            short_title = (safe_title[:35] + '...') if len(safe_title) > 35 else safe_title
            safe_name = name.encode('latin-1', 'replace').decode('latin-1')
            safe_cat = c.category.encode('latin-1', 'replace').decode('latin-1')
            safe_status = c.status.replace('_', ' ').capitalize().encode('latin-1', 'replace').decode('latin-1')

            pdf.cell(25, 8, str(c.complaint_id), 1)
            pdf.cell(65, 8, short_title, 1)
            pdf.cell(30, 8, safe_cat.capitalize(), 1)
            pdf.cell(30, 8, safe_status, 1)
            pdf.cell(40, 8, safe_name, 1, 1)
            
        # Return as downloadable file
        pdf_output = pdf.output()
        return send_file(
            BytesIO(pdf_output),
            mimetype='application/pdf',
            as_attachment=True,
            download_name='complaints_report.pdf'
        )

    # ================================================================== #
    #  ADMIN ROUTES                                                       #
    # ================================================================== #

    @app.route('/admin/dashboard')
    @login_required
    def admin_dashboard():
        if current_user.role != 'admin':
            abort(403)
        users = User.query.all()
        complaints = Complaint.query.all()
        return render_template('admin/dashboard.html', users=users, complaints=complaints)

    @app.route('/api/ping')
    def ping():
        return {"status": "ok", "message": "CCCS API is running"}

    return app



import sys

try:
    app = create_app()
except Exception as e:
    print(f"CRITICAL: Failed to create app: {e}", file=sys.stderr)
    raise

if __name__ == '__main__':
    app.run(debug=True, port=5000)

