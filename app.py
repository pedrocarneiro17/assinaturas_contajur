from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import base64
import io
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sua-chave-secreta-aqui-mude-em-producao'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///assinaturas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Filtro personalizado para templates
import json
@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value)
    except:
        return []

# Modelos do Banco de Dados
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(2), nullable=False)  # PF ou PJ
    documento = db.Column(db.String(18), unique=True, nullable=False)
    data_cadastro = db.Column(db.DateTime, default=datetime.utcnow)
    
class Documento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    competencia = db.Column(db.String(7), nullable=False)  # MM/YYYY
    situacoes = db.Column(db.Text, nullable=False)  # JSON string com [{situacao, departamento}]
    descricao = db.Column(db.Text)
    prazo_entrega = db.Column(db.Date, nullable=False)
    responsavel = db.Column(db.String(200), nullable=False)  # Quem está formalizando
    status = db.Column(db.String(20), default='pendente')  # pendente/assinado
    ordem = db.Column(db.Integer, default=0)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_assinatura = db.Column(db.DateTime)
    assinatura = db.Column(db.Text)  # Base64 da imagem
    
    cliente = db.relationship('Cliente', backref='documentos')

# Rotas
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = Usuario.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('dashboard'))
        
        return render_template('login.html', erro='Credenciais inválidas')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Filtros
    data_criacao = request.args.get('data_criacao')
    prazo_entrega = request.args.get('prazo_entrega')
    status_filtro = request.args.get('status')
    cliente_filtro = request.args.get('cliente')
    
    query = Documento.query
    
    if data_criacao:
        data_criacao_dt = datetime.strptime(data_criacao, '%Y-%m-%d')
        query = query.filter(db.func.date(Documento.data_criacao) == data_criacao_dt.date())
    if prazo_entrega:
        prazo_entrega_dt = datetime.strptime(prazo_entrega, '%Y-%m-%d').date()
        query = query.filter(Documento.prazo_entrega == prazo_entrega_dt)
    if status_filtro:
        query = query.filter(Documento.status == status_filtro)
    if cliente_filtro:
        query = query.filter(Documento.cliente_id == int(cliente_filtro))
    
    documentos = query.order_by(Documento.ordem, Documento.data_criacao.desc()).all()
    clientes = Cliente.query.all()
    
    return render_template('dashboard.html', documentos=documentos, clientes=clientes)

@app.route('/clientes')
def clientes():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template('clientes.html', clientes=clientes)

@app.route('/cliente/<int:id>/deletar', methods=['POST'])
def deletar_cliente(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    cliente = Cliente.query.get_or_404(id)
    
    # Verificar se há documentos vinculados
    if cliente.documentos:
        return jsonify({'erro': 'Não é possível excluir cliente com documentos vinculados'}), 400
    
    db.session.delete(cliente)
    db.session.commit()
    
    return jsonify({'sucesso': True})

@app.route('/cliente/novo', methods=['GET', 'POST'])
def novo_cliente():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        import re
        
        nome = request.form.get('nome')
        tipo = request.form.get('tipo')
        documento = request.form.get('documento').replace('.', '').replace('-', '').replace('/', '')
        
        # Validar CPF/CNPJ
        if tipo == 'PF':
            if len(documento) != 11 or not documento.isdigit():
                return render_template('cliente_form.html', erro='CPF inválido. Deve conter 11 dígitos.')
        else:  # PJ
            if len(documento) != 14 or not documento.isdigit():
                return render_template('cliente_form.html', erro='CNPJ inválido. Deve conter 14 dígitos.')
        
        # Formatar documento
        if tipo == 'PF':
            documento_formatado = f'{documento[:3]}.{documento[3:6]}.{documento[6:9]}-{documento[9:]}'
        else:
            documento_formatado = f'{documento[:2]}.{documento[2:5]}.{documento[5:8]}/{documento[8:12]}-{documento[12:]}'
        
        # Verificar se já existe
        if Cliente.query.filter_by(documento=documento_formatado).first():
            return render_template('cliente_form.html', erro='Este CPF/CNPJ já está cadastrado.')
        
        cliente = Cliente(nome=nome, tipo=tipo, documento=documento_formatado)
        db.session.add(cliente)
        db.session.commit()
        
        return redirect(url_for('clientes'))
    
    return render_template('cliente_form.html')

@app.route('/documento/novo', methods=['GET', 'POST'])
def novo_documento():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        import json
        
        cliente_id = request.form.get('cliente_id')
        competencia = request.form.get('competencia')
        situacoes_texto = request.form.getlist('situacoes[]')
        departamentos = request.form.getlist('departamentos[]')
        descricao = request.form.get('descricao')
        prazo_entrega = datetime.strptime(request.form.get('prazo_entrega'), '%Y-%m-%d').date()
        responsavel = request.form.get('responsavel')
        
        # Combinar situações com departamentos
        situacoes = []
        for i, sit in enumerate(situacoes_texto):
            if i < len(departamentos):
                situacoes.append({
                    'texto': sit,
                    'departamento': departamentos[i]
                })
        
        documento = Documento(
            cliente_id=cliente_id,
            competencia=competencia,
            situacoes=json.dumps(situacoes),
            descricao=descricao,
            prazo_entrega=prazo_entrega,
            responsavel=responsavel
        )
        
        db.session.add(documento)
        db.session.commit()
        
        return redirect(url_for('dashboard'))
    
    clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template('documento_form.html', clientes=clientes)

@app.route('/documento/<int:id>/assinar')
def assinar_documento(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    documento = Documento.query.get_or_404(id)
    return render_template('assinar.html', documento=documento)

@app.route('/documento/<int:id>/salvar-assinatura', methods=['POST'])
def salvar_assinatura(id):
    if 'user_id' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    
    documento = Documento.query.get_or_404(id)
    assinatura_base64 = request.json.get('assinatura')
    
    documento.assinatura = assinatura_base64
    documento.status = 'assinado'
    documento.data_assinatura = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({'sucesso': True})

@app.route('/cliente/<int:id>/historico')
def historico_cliente(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    cliente = Cliente.query.get_or_404(id)
    documentos = Documento.query.filter_by(cliente_id=id, status='assinado').order_by(Documento.data_assinatura.desc()).all()
    
    return render_template('historico.html', cliente=cliente, documentos=documentos)

@app.route('/documento/<int:id>/visualizar')
def visualizar_documento(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    documento = Documento.query.get_or_404(id)
    return render_template('visualizar.html', documento=documento)

@app.route('/api/documentos/reordenar', methods=['POST'])
def reordenar_documentos():
    if 'user_id' not in session:
        return jsonify({'erro': 'Não autenticado'}), 401
    
    ordem = request.json.get('ordem', [])
    
    for idx, doc_id in enumerate(ordem):
        documento = Documento.query.get(doc_id)
        if documento:
            documento.ordem = idx
    
    db.session.commit()
    return jsonify({'sucesso': True})

# Criar tabelas e usuário padrão
def init_db():
    with app.app_context():
        db.create_all()
        
        # Criar usuário padrão se não existir
        if not Usuario.query.filter_by(username='admin').first():
            user = Usuario(
                username='admin',
                password=generate_password_hash('admin123')
            )
            db.session.add(user)
            db.session.commit()
            print("Usuário padrão criado: admin / admin123")

init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
