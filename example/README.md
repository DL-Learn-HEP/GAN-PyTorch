Example commands: 
```bash
# Generator MNIST on CPU
$ python3 main.py mnist -e -g g-mnist -d d-mnist --pretrained 
```

```bash
# Generator MNIST on GPU
$ python3 main.py mnist -e -g g-mnist -d d-mnist --pretrained --gpu 0 --batch-size 128
```

