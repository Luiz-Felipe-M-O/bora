from django.shortcuts import render
from core.models import Evento


# Create your views here.
def tela_inicial(request):
    return render(request, 'index.html')


def lista_eventos(request):
    evento = Evento.objects.all()
    dados = {'eventos': evento}
    return render(request, 'evento.html', dados)


def criar_evento(request):
    return render(request, 'criar-evento.html')


def pesquisar_eventos(request):
    # Pega o que o usuário digitou no input (o name="q")
    query = request.GET.get('q')

    if query:
        eventos = Evento.objects.filter(titulo__icontains=query)
    else:
        eventos = Evento.objects.all()

    dados = {
        'eventos': eventos,
        'query': query
    }

    return render(request, 'evento.html', dados)