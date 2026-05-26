from django.contrib.auth.models import User
from django.db import models

# Create your models here.
class EmojiEvento(models.TextChoices):
    DEFAULT = '🎈', '🎈'
    FUTEBOL = '⚽', '⚽'
    CARTAS = '🃏', '🃏'
    XADREZ = '♟️', '♟️'
    TABULEIRO = '🎲', '🎲'
    BASQUETE = '🏀', '🏀'


class Evento(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    titulo = models.CharField(blank=False, null=False, max_length=100)
    descricao = models.TextField(null=True, blank=True)
    data_evento = models.DateTimeField(null=True, blank=True)
    data_criacao = models.DateTimeField(auto_now=True)
    local = models.CharField(blank=True, null=True, max_length=200)
    emoji = models.CharField(max_length=10, choices=EmojiEvento.choices, default=EmojiEvento.CARTAS)