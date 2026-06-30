from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Count
from django.utils.dateparse import parse_datetime
from core.models import Evento, Participante, OpcaoVotacao, Voto, MensagemChat, Rodada, PropostaPontuacao, VotoRodada, StatusEvento, StatusRodada
import datetime

def tela_inicial(request):
    evento_em_andamento = None
    if request.user.is_authenticated:
        participante = Participante.objects.filter(
            user=request.user,
            evento__status=StatusEvento.ONGOING
        ).select_related('evento').order_by('-evento__data_evento').first()
        if participante:
            evento_em_andamento = participante.evento

    context = {
        'evento_em_andamento': evento_em_andamento,
    }
    return render(request, 'index.html', context)

def lista_eventos(request):
    # 1. Busca todos os eventos ordenados (os mais recentes primeiro ou por status). Exceto os fechados.
    eventos = Evento.objects.exclude(status='CLOSED').order_by('status', 'data_evento')

    # 2. Captura os parâmetros da URL
    query = request.GET.get('q', '')
    filtro = request.GET.get('filtro', 'todos')

    # 3. Aplica o filtro de texto (barra de pesquisa)
    if query:
        eventos = eventos.filter(titulo__icontains=query)

    # 4. Aplica os filtros dos botões (abas)
    hoje = timezone.localtime().date()
    
    if filtro == 'hoje':
        eventos = eventos.filter(data_evento__date=hoje)
    elif filtro == 'semana':
        fim_semana = hoje + datetime.timedelta(days=7)
        eventos = eventos.filter(data_evento__date__range=[hoje, fim_semana])
    elif filtro == 'esportes':
        eventos = eventos.filter(emoji='🏸')
    elif filtro == 'jogos':
        eventos = eventos.filter(emoji__in=['🃏', '♟️', '🐉'])
    elif filtro == 'musica':
        eventos = eventos.filter(emoji='🎸')

    context = {
        'eventos': eventos,
        'query': query,
        'filtro_atual': filtro
    }
    return render(request, 'evento.html', context)

@login_required
def criar_evento(request):
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        descricao = request.POST.get('descricao')
        emoji = request.POST.get('emoji')
        local = request.POST.get('local')
        data = request.POST.get('data')
        hora = request.POST.get('hora')
        min_p = request.POST.get('min_participantes', 2)

        data_evento = None
        if data and hora:
            data_evento = datetime.datetime.strptime(
                f'{data} {hora}', '%Y-%m-%d %H:%M')
            data_evento = timezone.make_aware(data_evento)

        # Se o criador já definir data e local, pode pular direto para WAITING caso queira,
        # mas por padrão inicia em PLANNING para votação coletiva.
        status_inicial = StatusEvento.PLANNING
        if local and data_evento:
            status_inicial = StatusEvento.WAITING

        evento = Evento.objects.create(
            usuario=request.user,
            titulo=titulo,
            descricao=descricao,
            emoji=emoji,
            local=local,
            data_evento=data_evento,
            status=status_inicial,
            min_participantes=int(min_p)
        )

        Participante.objects.create(
            evento=evento, user=request.user, role='ORGANIZER', status='CONFIRMED')
        return redirect('/evento')

    return render(request, 'criar-evento.html')


@login_required
def perfil_usuario(request):
    participacoes = Participante.objects.filter(user=request.user).select_related(
        'evento').order_by('-evento__data_criacao')

    pontos_totais = sum(p.pontos_acumulados for p in participacoes)

    context = {
        'participacoes': participacoes,
        'pontos_totais': pontos_totais
    }
    return render(request, 'perfil.html', context)


@login_required
def detalhe_evento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    participante_atual = Participante.objects.filter(
        evento=evento, user=request.user).first()

    participantes = list(evento.participantes.all())
    opcoes_local = evento.opcoes_voto.filter(
        tipo='LOCAL').annotate(qtd_votos=Count('votos'))
    opcoes_data = evento.opcoes_voto.filter(
        tipo='DATA').annotate(qtd_votos=Count('votos'))
    mensagens = evento.mensagens.all().order_by('data_envio')
    rodada_atual = evento.rodadas.exclude(status=StatusRodada.APROVADA).first()
    historico_rodadas = evento.rodadas.filter(status=StatusRodada.APROVADA)

    contestou_rodada_atual = False
    if rodada_atual:
        # Preenche o formulário de (re)pontuação com o valor já registrado
        # para cada participante na rodada, quando houver — facilita tanto
        # a correção pelo organizador quanto a reproposta de quem contestou.
        pontos_atuais = {
            p.participante_id: p.pontos_ganhos for p in rodada_atual.propostas.all()
        }
        for p in participantes:
            p.pontos_proposta_atual = pontos_atuais.get(p.id, 0)

        if rodada_atual.status == StatusRodada.CONTESTADA:
            # Mesmo que várias pessoas tenham votado "Contestar", apenas a
            # primeira a fazê-lo (menor id, ou seja, primeira em ordem de
            # chegada) ganha o direito de repropor a pontuação. Isso evita
            # que o formulário de novo placar apareça simultaneamente para
            # todo mundo que contestou.
            primeiro_contestador = rodada_atual.votos_validacao.filter(
                concorda=False).order_by('id').first()
            contestou_rodada_atual = bool(
                primeiro_contestador and primeiro_contestador.user_id == request.user.id)

    context = {
        'evento': evento,
        'participante_atual': participante_atual,
        'participantes': participantes,
        'opcoes_local': opcoes_local,
        'opcoes_data': opcoes_data,
        'mensagens': mensagens,
        'rodada_atual': rodada_atual,
        'historico_rodadas': historico_rodadas,
        'contestou_rodada_atual': contestou_rodada_atual,
    }
    return render(request, 'detalhe_evento.html', context)


@login_required
def status_evento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    rodada_atual = evento.rodadas.exclude(status=StatusRodada.APROVADA).first()
    
    votos_local = sum(o.total_votos() for o in evento.opcoes_voto.filter(tipo='LOCAL'))
    votos_data = sum(o.total_votos() for o in evento.opcoes_voto.filter(tipo='DATA'))

    # Retiramos 'evento.mensagens.count()' daqui para não disparar o reload da página inteira!
    estado = (
        evento.status,
        evento.participantes.count(),
        evento.participantes.filter(status='CONFIRMED').count(),
        evento.opcoes_voto.filter(tipo='LOCAL').count(),
        evento.opcoes_voto.filter(tipo='DATA').count(),
        votos_local,
        votos_data,
        rodada_atual.id if rodada_atual else None,
        rodada_atual.status if rodada_atual else None,
        rodada_atual.votos_validacao.count() if rodada_atual else 0,
    )

    fingerprint = hash(estado)

    # Prepara as mensagens do chat para atualizar silenciosamente no front-end
    mensagens = [
        {
            'texto': m.texto,
            'autor': m.user.username,
            'is_minha': m.user == request.user
        }
        for m in evento.mensagens.all().order_by('data_envio')
    ]

    return JsonResponse({
        'fingerprint': fingerprint,
        'mensagens': mensagens
    })


@login_required
def demonstrar_interesse(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    tipo_acao = request.POST.get('acao')  # 'INTERESTED' ou 'CONFIRMED'

    participante, created = Participante.objects.get_or_create(
        evento=evento, user=request.user,
        defaults={'status': tipo_acao, 'role': 'PLAYER'}
    )
    if not created:
        participante.status = tipo_acao
        participante.save()

    # Transição automática de Estado se atingir o mínimo de confirmados (Percepção de Espaço)
    if evento.status == StatusEvento.WAITING:
        confirmados = evento.participantes.filter(status='CONFIRMED').count()
        if confirmados >= evento.min_participantes:
            evento.status = StatusEvento.ONGOING
            evento.save()

    return redirect(f'/evento/{evento.id}')


@login_required
def sugerir_opcao(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    eh_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        tipo = request.POST.get('tipo')  # 'LOCAL' ou 'DATA'
        valor = request.POST.get('valor')

        if tipo in ('LOCAL', 'DATA') and valor:
            opcao = OpcaoVotacao.objects.create(
                evento=evento, tipo=tipo, valor=valor)

            # Quem sugere já considera aquela a melhor opção: o voto do
            # próprio autor entra junto, na mesma regra de "um voto por
            # tipo" usada em votar_enquete (troca qualquer voto anterior
            # do usuário nesse tipo de opção).
            Voto.objects.filter(opcao__evento=evento,
                                 opcao__tipo=tipo, user=request.user).delete()
            Voto.objects.create(opcao=opcao, user=request.user)

            if eh_ajax:
                return JsonResponse({
                    'ok': True,
                    'opcao': {
                        'id': opcao.id,
                        'tipo': opcao.tipo,
                        'valor': opcao.valor,
                        'qtd_votos': 1,
                    },
                })
        elif eh_ajax:
            return JsonResponse(
                {'ok': False, 'erro': 'Preencha a sugestão antes de enviar.'}, status=400)

    if eh_ajax:
        return JsonResponse({'ok': False, 'erro': 'Não foi possível registrar a sugestão.'}, status=400)
    return redirect(f'/evento/{evento.id}')


@login_required
@require_POST
def votar_enquete(request, opcao_id):
    opcao = get_object_or_404(OpcaoVotacao, id=opcao_id)
    eh_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # Remove votos anteriores do mesmo usuário para o mesmo tipo de opção no evento
    Voto.objects.filter(opcao__evento=opcao.evento,
                        opcao__tipo=opcao.tipo, user=request.user).delete()
    Voto.objects.create(opcao=opcao, user=request.user)

    if eh_ajax:
        # O voto pode ter mudado a contagem de mais de uma opção (a antiga
        # perdeu o voto, a nova ganhou), então devolve todas do mesmo tipo.
        opcoes = opcao.evento.opcoes_voto.filter(
            tipo=opcao.tipo).annotate(qtd=Count('votos'))
        return JsonResponse({
            'ok': True,
            'tipo': opcao.tipo,
            'opcoes': [{'id': o.id, 'qtd_votos': o.qtd} for o in opcoes],
        })

    return redirect(f'/evento/{opcao.evento.id}')


@login_required
def fechar_planejamento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    if evento.usuario == request.user and evento.status == StatusEvento.PLANNING:
        # Só busca/sobrescreve o que ainda não foi definido, para não perder
        # um valor já confirmado em uma rodada anterior de votação.
        if not evento.local:
            top_local = evento.opcoes_voto.filter(tipo='LOCAL').annotate(
                qtd=Count('votos')).order_by('-qtd').first()
            if top_local:
                evento.local = top_local.valor

        if not evento.data_evento:
            top_data = evento.opcoes_voto.filter(tipo='DATA').annotate(
                qtd=Count('votos')).order_by('-qtd').first()
            if top_data:
                # parse_datetime aceita variações do formato ISO 8601
                # (com ou sem segundos), evitando falha silenciosa do strptime.
                data_dt = parse_datetime(top_data.valor)
                if data_dt is not None:
                    if timezone.is_naive(data_dt):
                        data_dt = timezone.make_aware(data_dt)
                    evento.data_evento = data_dt

        # Só avança o evento para WAITING quando local e data realmente
        # ficaram definidos. Caso contrário, permanece em PLANNING para que
        # a tela de votação continue disponível e novas sugestões possam
        # ser feitas — antes isso avançava o status mesmo sem dados, e o
        # evento ficava travado sem nunca exibir data/local no card.
        if evento.local and evento.data_evento:
            evento.status = StatusEvento.WAITING

        evento.save()  # ESSENCIAL: Isso persiste a mudança no banco de dados
    return redirect(f'/evento/{evento.id}')


@login_required
def enviar_mensagem(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    eh_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST' and evento.status in [StatusEvento.WAITING, StatusEvento.ONGOING]:
        texto = request.POST.get('texto', '').strip()
        if texto:
            mensagem = MensagemChat.objects.create(
                evento=evento, user=request.user, texto=texto)
            if eh_ajax:
                return JsonResponse({
                    'ok': True,
                    'mensagem': {
                        'id': mensagem.id,
                        'texto': mensagem.texto,
                        'autor': mensagem.user.username,
                    },
                })
        elif eh_ajax:
            return JsonResponse(
                {'ok': False, 'erro': 'Digite uma mensagem antes de enviar.'}, status=400)

    if eh_ajax:
        return JsonResponse({'ok': False, 'erro': 'Não foi possível enviar a mensagem.'}, status=400)
    return redirect(f'/evento/{evento.id}')


@login_required
def gerenciar_rodada(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    if evento.status != StatusEvento.ONGOING:
        return redirect(f'/evento/{evento.id}')

    if request.method == 'POST':
        acao = request.POST.get('acao')  # 'INICIAR' ou 'PROPOR_PONTUACAO'

        if acao == 'INICIAR':
            # Só o organizador inicia uma nova rodada de jogo.
            if evento.usuario == request.user:
                qtd_rodadas = evento.rodadas.count()
                Rodada.objects.create(evento=evento, numero=qtd_rodadas + 1)

        elif acao == 'PROPOR_PONTUACAO':
            participante_atual = evento.participantes.filter(
                user=request.user).first()
            rodada = evento.rodadas.filter(
                status__in=[StatusRodada.PONTUACAO, StatusRodada.CONTESTADA]
            ).first()

            if rodada and participante_atual:
                # Quem pode propor pontuação:
                # - estado PONTUACAO (1ª proposta da rodada): só o organizador.
                # - estado CONTESTADA (reproposta): apenas a primeira pessoa
                #   que contestou, já que só ela assume a nova pontuação.
                pode_propor = False
                if rodada.status == StatusRodada.PONTUACAO and evento.usuario == request.user:
                    pode_propor = True
                elif rodada.status == StatusRodada.CONTESTADA:
                    # Apenas a primeira pessoa que contestou (menor id entre
                    # os votos "não") tem permissão de repropor a pontuação.
                    # Isso é reforçado aqui no backend, e não só na UI, para
                    # que ninguém contorne a regra enviando o POST direto.
                    primeiro_contestador = rodada.votos_validacao.filter(
                        concorda=False).order_by('id').first()
                    pode_propor = bool(
                        primeiro_contestador and primeiro_contestador.user_id == request.user.id)

                if pode_propor:
                    for participante in evento.participantes.all():
                        pts = request.POST.get(f'pontos_{participante.id}', 0)
                        PropostaPontuacao.objects.update_or_create(
                            rodada=rodada, participante=participante,
                            defaults={
                                'pontos_ganhos': int(pts),
                                'proposto_por': request.user,
                            },
                        )
                    # Reseta votos anteriores e abre uma nova votação sobre
                    # a pontuação recém-proposta.
                    VotoRodada.objects.filter(rodada=rodada).delete()
                    rodada.status = StatusRodada.VOTACAO
                    rodada.save()

    return redirect(f'/evento/{evento.id}')


@login_required
@require_POST
def votar_placar_rodada(request, rodada_id):
    rodada = get_object_or_404(Rodada, id=rodada_id)

    # Só é possível votar enquanto a rodada está, de fato, em votação.
    if rodada.status != StatusRodada.VOTACAO:
        return redirect(f'/evento/{rodada.evento.id}')

    concorda = request.POST.get('concorda') == 'sim'

    VotoRodada.objects.update_or_create(
        rodada=rodada, user=request.user,
        defaults={'concorda': concorda}
    )

    # Validação Democrática Compartilhada: a maioria decide o destino da
    # pontuação proposta. Se aprovar, os pontos consolidam-se no perfil de
    # cada jogador; se contestar, a rodada volta para quem contestou definir
    # uma nova pontuação (estado CONTESTADA), recomeçando o ciclo de votação.
    total_participantes = rodada.evento.participantes.count()
    votos_favoraveis = rodada.votos_validacao.filter(concorda=True).count()
    votos_contrarios = rodada.votos_validacao.filter(concorda=False).count()

    if votos_favoraveis > (total_participantes / 2):
        rodada.status = StatusRodada.APROVADA
        rodada.save()
        # Atualiza a pontuação permanente do perfil dos jogadores (Memória do Grupo)
        for proposta in rodada.propostas.all():
            proposta.participante.pontos_acumulados += proposta.pontos_ganhos
            proposta.participante.save()
    elif votos_contrarios > (total_participantes / 2):
        rodada.status = StatusRodada.CONTESTADA
        rodada.save()

    return redirect(f'/evento/{rodada.evento.id}')


@login_required
def encerrar_evento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    if evento.usuario == request.user:
        evento.status = StatusEvento.CLOSED
        evento.save()
    return redirect(f'/evento/{evento.id}')


@login_required
@require_POST
def excluir_evento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    # Só o organizador pode excluir, e apenas enquanto o evento ainda está em
    # planejamento (sem data/local definidos, sem rodadas ou histórico).
    if evento.usuario == request.user and evento.status == StatusEvento.PLANNING:
        evento.delete()
        return redirect('/evento')
    return redirect(f'/evento/{evento.id}')

# Mantidas as Views de Auth originais fornecidas


def login_view(request):
    erro = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(request.GET.get('next', '/'))
        else:
            erro = 'Usuário ou senha incorretos.'
    return render(request, 'login.html', {'erro': erro})


def logout_view(request):
    logout(request)
    return redirect('/')


def cadastro_view(request):
    erro = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        if password1 != password2:
            erro = 'As senhas não coincidem.'
        elif User.objects.filter(username=username).exists():
            erro = 'Este nome de usuário já está em uso.'
        else:
            user = User.objects.create_user(
                username=username, password=password1)
            login(request, user)
            return redirect('/')
    return render(request, 'cadastro.html', {'erro': erro})