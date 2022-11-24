import itertools
import csv
import fire
import torch.nn.functional as F
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import roc_auc_score
import tokenization
import train
import random
import numpy as np
from utils import set_seeds, get_device, truncate_tokens_pair
import re
from nltk.corpus import stopwords 
from nltk.tokenize import word_tokenize 
from nltk.stem.wordnet import WordNetLemmatizer 
from torch.nn import functional
from torch import LongTensor
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence
import os
#os.environ["CUDA_VISIBLE_DEVICES"] = '1'
class CsvDataset(Dataset):
    """ Dataset Class for CSV file """
    labels = None
    
    def __init__(self, file, pipeline=[]): # cvs file and pipeline object
        Dataset.__init__(self)
        data = []

        with open(file, "r", encoding='utf-8') as f:
            # list of splitted lines : line is also list
            lines = csv.reader(f, delimiter='\t')

            for instance in self.get_instances(lines): # instance : tuple of fields
                for proc in pipeline: # a bunch of pre-processing
                    
                    instance = proc(instance)
                data.append(instance)

        # To Tensors
   
        self.tensors = [torch.tensor(x, dtype=torch.long) for x in zip(*data)]
        
    def __len__(self):
        return self.tensors[0].size(0)

    def __getitem__(self, index):
        return [tensor[index] for tensor in self.tensors]

    def get_instances(self, lines):
        """ get instance array from (csv-separated) line list """
        raise NotImplementedError

class MRPC(CsvDataset):
    """ Dataset class for MRPC """
    labels = ("0", "1") # label names
    def __init__(self, file, pipeline=[]):
        super().__init__(file, pipeline)

    def get_instances(self, lines):
        for line in itertools.islice(lines, 0, None): # skip header

            yield line[0], line[1].encode('utf8'),None # label, text_a, text_b

            

class MNLI(CsvDataset):
    """ Dataset class for MNLI """
    labels = ("contradiction", "entailment", "neutral") # label names
    def __init__(self, file, pipeline=[]):
        super().__init__(file, pipeline)

    def get_instances(self, lines):
        for line in itertools.islice(lines, 0, None): # skip header
            yield line[-1], line[8], line[9] # label, text_a, text_b


def dataset_class(task):
    """ Mapping from task string to Dataset Class """
    table = {'mrpc': MRPC, 'mnli': MNLI}
    return table[task]


class Pipeline():
    """ Preprocess Pipeline Class : callable """
    def __init__(self):
        super().__init__()

    def __call__(self, instance):
        raise NotImplementedError


class Tokenizing(Pipeline):
    """ Tokenizing sentence pair """
    def __init__(self, preprocessor, tokenize):
        super().__init__()
        self.preprocessor = preprocessor # e.g. text normalization
        self.tokenize = tokenize # tokenize function

    def __call__(self, instance):
        label, text_a, text_b = instance

        label = self.preprocessor(label)
        tokens_a = self.tokenize(self.preprocessor(text_a))
        tokens_b = self.tokenize(self.preprocessor(text_b)) \
                   if text_b else []

        return (label, tokens_a, tokens_b)

    

class AddSpecialTokensWithTruncation(Pipeline):
    """ Add special tokens [CLS], [SEP] with truncation """
    def __init__(self, max_len=512):
        super().__init__()
        self.max_len = max_len

    def __call__(self, instance):
        label, tokens_a, tokens_b  = instance

        #print(tokens_a)
        _max_len = self.max_len - 3 if tokens_b else self.max_len - 2
        truncate_tokens_pair(tokens_a, tokens_b, _max_len)
        # -3 special tokens for [CLS] text_a [SEP] text_b [SEP]
        # -2 special tokens for [CLS] text_a [SEP]
     
        
        # Add Special Tokens
        tokens_a = tokens_a 
        #print(label)

        return (label, tokens_a)


class TokenIndexing(Pipeline):
    """ Convert tokens into token indexes and do zero-padding """
    def __init__(self, indexer, labels, max_len=512):
        super().__init__()
        self.indexer = indexer # function : tokens to indexes
        # map from a label name to a label index
        self.label_map = {name: i for i, name in enumerate(labels)}
        self.max_len = max_len

    def __call__(self, instance):
        label, tokens_a = instance
        input_ids = self.indexer(tokens_a )
        seq_lengths = len(input_ids)
        segment_ids = [0]*len(tokens_a) # token type ids
        input_mask = [1]*len(tokens_a)
        label_id = self.label_map[label]
        # zero padding
        n_pad = self.max_len - len(input_ids)
        input_ids.extend([0]*n_pad)
        segment_ids.extend([0]*n_pad)
        input_mask.extend([0]*n_pad)

        return (input_ids, segment_ids, input_mask, label_id,seq_lengths)

'''
class Classifier_Attention_LSTM(nn.Module):
    """ Classifier with Transformer """
    def __init__(self,  n_labels):
        super().__init__()
        self.activ = nn.Tanh()
        self.classifier = nn.Linear(300, n_labels)
        self.rnn = nn.LSTM(300, 300, batch_first=True)
        self.softmax_word = nn.Softmax()

    def attention_net(self,lstm_output, final_state):
        hidden = final_state.squeeze(0)
        
        attn_weights = torch.bmm(lstm_output, hidden.unsqueeze(2)).squeeze(2)
        soft_attn_weights = F.softmax(attn_weights, 1)
        new_hidden_state = torch.bmm(lstm_output.transpose(1, 2), soft_attn_weights.unsqueeze(2)).squeeze(2)
        return new_hidden_state,soft_attn_weights

    def forward(self,token2, input_ids, segment_ids, input_mask,seq_lengths):
        packed_input = pack_padded_sequence(token2, seq_lengths.cpu().numpy(), batch_first=True)
        packed_output,(final_hidden_state, final_cell_state) = self.rnn(packed_input)
        r_output, input_sizes = pad_packed_sequence(packed_output, batch_first=True)
        attn_output,soft_attn_weights = self.attention_net(r_output, r_output[:,-1,:])
        print("soft_attn_weights#:", soft_attn_weights)
        print("soft_attn_weights#:",soft_attn_weights.shape)
        logits = self.classifier(attn_output)
        return logits,soft_attn_weights

'''
class Classifier_Attention_LSTM(nn.Module):
    def __init__(self,  n_labels):
        super().__init__()
        self.rnn = nn.LSTM(300, 300, batch_first=True)
        self.tanh1 = nn.Tanh()
        self.w = nn.Parameter(torch.zeros(300))
        self.tanh2 = nn.Tanh()
        self.fc1 = nn.Linear(300,n_labels)

    def forward(self,token2, input_ids, segment_ids, input_mask,seq_lengths):
        packed_input = pack_padded_sequence(token2, seq_lengths.cpu().numpy(), batch_first=True)
        packed_output,(final_hidden_state, final_cell_state) = self.rnn(packed_input)
        r_output, input_sizes = pad_packed_sequence(packed_output, batch_first=True)
        output = r_output
        #output = self.tanh1(r_output)  # [128, 32, 256]
        # M = torch.tanh(torch.matmul(H, self.u))

        #print("##torch.matmul(output, self.w)##:", torch.matmul(output, self.w))
        alpha = F.softmax(torch.matmul(output, self.w)).unsqueeze(-1)  # [128, 32, 1]
        
        #print("####:", alpha.squeeze())
        
        out = r_output * alpha  # [128, 32, 256]
        out = torch.sum(out, 1)  # [128, 256]
        out = F.relu(out)
        out = self.fc1(out)
        return out, alpha.squeeze()

class Classifier_CNN(nn.Module):
    """ Classifier with Transformer """
    def __init__(self, n_labels):
        super().__init__()
        self.Lin1 = nn.Linear(100,n_labels)
        self.activ = nn.Tanh()
        self.drop = nn.Dropout(0.5)
        self.fc1 = nn.Linear(300, n_labels)  # a dense layer for classification
        self.convs_1d = nn.ModuleList([
            nn.Conv2d(1, 100, (k, 300)) 
            for k in [3,4,5]])
        
    def conv_and_pool(self, x, conv,x1):
        x = conv(x)
        x = F.relu(x)
        x = x.squeeze(3)
        x = F.max_pool1d(x, x.size(2)).squeeze(2)
        return x

    def forward(self, token2, input_ids, segment_ids, input_mask):
        embeds = token2.unsqueeze(1)
        conv_results = [self.conv_and_pool(embeds, conv,input_ids) for conv in self.convs_1d]
        x = torch.cat(conv_results, 1)
        logits = self.fc1(self.drop(x))
        return logits,logits 
    
    

    
    
def matching_blacklist(abusive_set, input_sentence):
    result_list = list()
    for i,abusive_word in enumerate(abusive_set):
        input_sentence2 = re.sub("[^a-zA-Z]","",input_sentence).strip().lower()
        if abusive_word.lower() in input_sentence2:
            input_split = input_sentence.split(" ")
            for j,input_word in enumerate(input_split):
                input_word2 = re.sub("[^a-zA-Z]","",input_word).strip()
                if(input_word2.lower() in abusive_word.lower()): 
                    result_list.append(abusive_word)
                    break
                    
    return result_list


def matching_blacklist2(abusive_set, input_sentence, temp):
    result_list = list()
    for i,abusive_word in enumerate(abusive_set):
        input_sentence2 = input_sentence.lower().split(' ')
        abusive_word2 = abusive_word.split(' ')
        flag=0
        for l in range(0, len(abusive_word2)):
            for input in input_sentence2:
                if abusive_word2[l].lower() in input:
                    if(len(abusive_word2[l]) >= len(input)-3):
                        #print(abusive_word2[l])
                        flag+=1
                        break
                        
        if(flag == temp):
            result_list.append(abusive_word)
                    
    return result_list


def main(task='mrpc',
         train_cfg='config/train_mrpc.json',
         data_parallel=True,
         data_train_file='total_data/imdbtrain.tsv',
         data_test_file='total_data/IMDB_test.tsv',
         dataName='IMDB',
         stopNum=250,
         max_len=300,
         mode='train'):

    
   

    if mode == 'train':
        def get_loss_CNN(model, batch, global_step): # make sure loss is a scalar tensor
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch

            token1 = embedding(input_ids.long())
            
            logits,attention_score = model(token1.to(device=get_device()),input_ids, segment_ids, input_mask)
            
            loss1 = criterion(logits, label_id)   
            return loss1
        
        def evalute_CNN(model, batch,global_step,ls):
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch
            token1 = embedding(input_ids.long())
            logits,attention_score = model(token1.to(device=get_device()),input_ids, segment_ids, input_mask)
            logits=F.softmax(logits)

            y_pred11, y_pred1 = logits.max(1)
            


            return label_id, logits
        
        def get_loss_Attn_LSTM(model, batch, global_step): # make sure loss is a scalar tensor
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch
            
            seq_lengths, perm_idx = seq_lengths.sort(0, descending=True)
            input_ids = input_ids[perm_idx]
            label_id = label_id[perm_idx]
            token1 = embedding(input_ids.long())
            
            logits,attention_score = model(token1.to(device=get_device()),input_ids, segment_ids, input_mask,seq_lengths)
            
            loss1 = criterion(logits, label_id)   
            return loss1
        
        
        def evalute_Attn_LSTM(model, batch,global_step,ls):
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch
            
            seq_lengths, perm_idx = seq_lengths.sort(0, descending=True)
            input_ids = input_ids[perm_idx]
            label_id = label_id[perm_idx]
            token1 = embedding(input_ids.long())
            
            
            logits,attention_score = model(token1.to(device=get_device()),input_ids, segment_ids, input_mask,seq_lengths)
            logits=F.softmax(logits)

            y_pred11, y_pred1 = logits.max(1)
            
         
            return label_id, logits
        
        
        def generating_lexiocn(model, model2, batch,global_step,ls, e):
            if(global_step== 0):
                result3.clear()
                result_label.clear()
                bb_11.clear()
                bb_22.clear()
                    
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch
            
            seq_lengths, perm_idx = seq_lengths.sort(0, descending=True)
            input_ids = input_ids[perm_idx]
            label_id = label_id[perm_idx]
            token1 = embedding(input_ids.long())
            logits,attention_score = model(token1.to(device=get_device()),input_ids, segment_ids, input_mask)
            logits2,attention_score2 = model2(token1.to(device=get_device()),input_ids, segment_ids, input_mask,seq_lengths)

            logits=F.softmax(logits)
            #logits2=F.softmax(logits2)
            y_pred11, y_pred1 = logits.max(1)
            y_pred22, y_pred2 = logits2.max(1)
            atten, attn_s1 = attention_score2.max(1)
            atte2, attn_s2 = torch.topk(attention_score2, 4)
            
            for i in range(0, len(input_ids)):
               

                
                split_tokens = []
                att_index=[]
                for token in tokenizer.tokenize(data0[global_step*128+perm_idx[i]]): 
                    split_tokens.append(token)
                
                if(len(split_tokens) <= attn_s1[i].item()):  
                    attn_index3 = attention_score[i][:len(split_tokens)-1]
                    attn_num ,attn_index2 = attn_index3.max(0)
                    attn_index = attn_index2.item()
                else:
                    for j in range(0, 4):
                        att_index.append(attn_s2[i][j].item())
                    
                tok=[]
                if(atten[i].item()<= 0):
                    token_ab=split_tokens[0]
                else:
                    for j in range(0,len(att_index)):
                        if(att_index[j] >= len(split_tokens)):
                            continue
                        tok.append(split_tokens[att_index[j]])
                        
                token_temp = data0[global_step*128+perm_idx[i]].split(' ')
                token2 = []
                for kk in range(0,len(tok)):
                    token_ab = tok[kk]
                    token_ab=token_ab.replace(".", "")
                    token_ab=token_ab.replace(",", "")
                    token_ab=token_ab.replace("'", "")
                    token_ab=token_ab.replace("!", "")
                    token_ab=token_ab.replace("?", "")
                    token_ab=token_ab.replace("'", "")
                    token_ab=token_ab.replace('"', "")
                    if(token_ab == '' or token_ab == ' ' or token_ab ==',' or token_ab=='.' or token_ab == 'from' or token_ab == 'are' or token_ab == 'is' or token_ab == 'and' or token_ab == 'with' or token_ab == 'may' or token_ab == 'would' or token_ab == 'could' or token_ab == 'have' or token_ab == 'has' or token_ab == 'had' or token_ab == 'was' or token_ab == 'were' or token_ab == 'this' or token_ab == 'who' or token_ab == 'that' or token_ab == 'www' or token_ab == 'http' or token_ab == 'com' or token_ab == 'those' or token_ab == 'your' or token_ab == 'not' or token_ab == 'seem' or token_ab == 'too' or token_ab == 'lol'or token_ab == 'but' or token_ab == 'these' or token_ab == 'their' or token_ab == 'can' or token_ab == 'there' or token_ab == 'gave' or token_ab == 'his'  or token_ab == 'etc' or token_ab == 'thats' or token_ab == 'though' or token_ab == 'off' or token_ab == 'she' or token_ab == 'them' or token_ab == 'huh' or token_ab == 'why' or token_ab == 'wont' or token_ab == 'any' or token_ab == 'some' or token_ab == 'its' or token_ab == 'yeah' or token_ab == 'yes' or token_ab == 'you' or token_ab == 'should' or token_ab == 'dont' or token_ab == 'anybody' or token_ab == 'than' or token_ab == 'where' or token_ab == 'for' or token_ab == 'more' or token_ab == 'will' or token_ab == 'him' or token_ab == 'its' or token_ab == 'your' or token_ab == 'wii' or token_ab == 'having' or token_ab == 'just' or token_ab == 'help'  or token_ab == 'helps' or token_ab == 'all' or token_ab == 'they' or token_ab == 'take' or token_ab == 'the' or token_ab == 'what' or token_ab == 'need' or token_ab == 'make' or token_ab == 'about' or token_ab == 'then' or token_ab == 'when' or token_ab == 'does' or token_ab == 'ask'  or token_ab == 'much' or token_ab == 'man' or token_ab == 'know' or token_ab == 'how' or token_ab == 'look' or token_ab == 'like' or token_ab == 'one' or token_ab == 'think' or token_ab == 'tell' or token_ab == 'find' or token_ab == 'cant' or token_ab == 'now' or token_ab == 'try' or token_ab == 'give' or token_ab == 'answer' or token_ab == 'her' or token_ab == 'out' or token_ab == 'get' or token_ab == 'because'  or token_ab == 'myself' or token_ab == 'wants' or token_ab == 'movie' or token_ab == 'film' or token_ab == 'films') : 
                        continue
                        
                    if(len(token_ab) < 2):
                        continue

                    for gge, input_word in enumerate(token_temp):
                        
                        
                        if(token_ab.lower() in input_word.lower()):
                            input_word=input_word.replace(".", "")
                            input_word=input_word.replace(",", "")
                            input_word=input_word.replace("'", "")
                            input_word=input_word.replace("!", "")
                            input_word=input_word.replace("?", "")
                            input_word=input_word.replace("'", "")
                            input_word=input_word.replace('"', "")

                            token2.append(input_word.lower())
                            break
                token2 = list(set(token2))
                
                if(len(token2) < 3):
                    continue
               #print(token2)
                sen=""
                for l in range(0, len(token2)-1):
                    sen+=token2[l]+' '
                sen+=token2[len(token2)-1]
                if(y_pred2[i]==0 and  y_pred1[i]==0 ):
                    try:
                        bb_11[sen]+=y_pred22[i]
                    except KeyError:
                        bb_11[sen]=y_pred22[i]
                           

                if(y_pred2[i]==1  and y_pred1[i]==1 ):
                    try:
                        bb_22[sen]+=y_pred22[i]
                    except KeyError:
                        bb_22[sen]=y_pred22[i]



            
            if(global_step==ls-1):
                
                
                abusive_11.clear()
                abusive_22.clear()
               
                            
                bb_11_up = sorted(bb_11.items(),key=lambda x: x[1], reverse=True)
                bb_22_up = sorted(bb_22.items(),key=lambda x: x[1], reverse=True)
            
                lexicon_size = 50 
                bb_11_up = bb_11_up[:lexicon_size]
                bb_22_up = bb_22_up[:lexicon_size]
              

                for i in bb_11_up:
                    flag=0
                    for j in bb_22_up:
                        if((i[0].lower() in j[0].lower()) or (j[0].lower() in i[0].lower())):
                            if(i[1] < j[1]):
                                flag=1
                                break


                    if(flag==0):
                        abusive_11.append(i[0])
                        
                        
                        
                for i in bb_22_up:
                    flag=0
                    for j in bb_11_up:
                        if((i[0].lower() in j[0].lower()) or (j[0].lower() in i[0].lower())):
                            if(i[1] < j[1]):
                                flag=1
                                break


                    if(flag==0):
                        abusive_22.append(i[0])

                ddf = open("./IMDB_Lexicon/imdbLexicon_1.txt",'w', encoding='UTF8')

                for i in range(0, len(abusive_11)):
                    ddf.write(abusive_11[i]+'\n')
                    
                ddf.close()
                

                
                ddf = open("./IMDB_Lexicon/imdbLexicon_2.txt",'w', encoding='UTF8')

                for i in range(0, len(abusive_22)):
                    ddf.write(abusive_22[i]+'\n')
                    
                ddf.close()
            return label_id, logits
        

        def evalute_CNN_SSL(model, batch):
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch
            token1 = embedding(input_ids.long())
            logits,attention_score = model(token1.to(device=get_device()),input_ids, segment_ids, input_mask)

            return label_id, logits
        
        def pseudo_labeling(model,model2, batch, global_step,ls,e):
            if(global_step== 0):
                result3.clear()
                result4.clear()

                label_0.clear()
                label_1.clear()


                result_label.clear()


                
                abusive_11.clear()
                abusive_22.clear()

                
                abusive_dic_file = open("./IMDB_Lexicon/imdbLexicon_1.txt",'r', encoding='UTF8')              
                for line in abusive_dic_file.read().split('\n'):
                    if(len(line)<=3):
                        continue
                    abusive_11.append(line) 
                abusive_dic_file.close()
                
                
                abusive_dic_file = open("./IMDB_Lexicon/imdbLexicon_2.txt",'r', encoding='UTF8')              
                for line in abusive_dic_file.read().split('\n'):
                    if(len(line)<=3):
                        continue
                    abusive_22.append(line) 
                abusive_dic_file.close()

                
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch
            
            seq_lengths, perm_idx = seq_lengths.sort(0, descending=True)
            input_ids = input_ids[perm_idx]
            label_id = label_id[perm_idx]
            token1 = embedding(input_ids.long())
            
            
            logits,attention_score = model(token1.to(device=get_device()),input_ids, segment_ids, input_mask)
            logits2,attention_score2 = model2(token1.to(device=get_device()),input_ids, segment_ids, input_mask,seq_lengths)
            
            
            logits=F.softmax(logits)
            logits2=F.softmax(logits2)
            logits3 = logits + logits2
            y_pred33, y_pred3 = logits3.max(1)
            y_pred11, y_pred1 = logits.max(1)
            y_pred22, y_pred2 = logits2.max(1)

            label_id2=[]
 
            for i in range(0, len(input_ids)):
                input_sentence = data0[global_step*128+perm_idx[i]]
                input_sentence =re.sub("[!@#$%^&*().?\"~/<>:;'{}]","",input_sentence)

               
                abusive_word_list_neg11 = list()
                abusive_word_list_neg11 += matching_blacklist2(abusive_11, input_sentence,3)
                abusive_word_list_neg11 = list((set(abusive_word_list_neg11)))
                
                abusive_word_list_neg22 = list()
                abusive_word_list_neg22 += matching_blacklist2(abusive_22, input_sentence,3)
                abusive_word_list_neg22 = list((set(abusive_word_list_neg22)))
                
                abusive_word_list_neg111 = list()
                abusive_word_list_neg111 += matching_blacklist2(abusive_11, input_sentence,4)
                abusive_word_list_neg111 = list((set(abusive_word_list_neg111)))
                
                abusive_word_list_neg222 = list()
                abusive_word_list_neg222 += matching_blacklist2(abusive_22, input_sentence,4)
                abusive_word_list_neg222 = list((set(abusive_word_list_neg222)))
                
        
                
                
                a = max(len(abusive_word_list_neg11), len(abusive_word_list_neg22))
                aa = max(len(abusive_word_list_neg111), len(abusive_word_list_neg222))
                        

                if (( a>=1 and len(abusive_word_list_neg11)>len(abusive_word_list_neg22) and y_pred1[i].item()==0 and y_pred11[i].item()>=0.9) or ( a>=1 and len(abusive_word_list_neg11)>len(abusive_word_list_neg22) and y_pred2[i].item()==0 and y_pred22[i].item()>=0.9) ):
                    label_0.append(0)
                    result4.append([global_step*128+perm_idx[i], 0,data0[global_step*128+perm_idx[i]],label_id[perm_idx[i]].item()])
                elif(( a>=1 and len(abusive_word_list_neg11)<len(abusive_word_list_neg22) and y_pred1[i].item()==1 and y_pred11[i].item()>=0.9) or ( a>=1 and len(abusive_word_list_neg11)<len(abusive_word_list_neg22) and y_pred2[i].item()==1 and y_pred22[i].item()>=0.9) ):
                    label_1.append(1)
                    result4.append([global_step*128+perm_idx[i], 1,data0[global_step*128+perm_idx[i]],label_id[perm_idx[i]].item()])
               
                elif(aa>=1 and len(abusive_word_list_neg111)>len(abusive_word_list_neg222) ):
                    label_0.append(0)
                    result4.append([global_step*128+perm_idx[i], 0,data0[global_step*128+perm_idx[i]],label_id[perm_idx[i]].item()])
                elif(aa>=1 and len(abusive_word_list_neg111)<len(abusive_word_list_neg222) ):
                    label_1.append(1)
                    result4.append([global_step*128+perm_idx[i], 1,data0[global_step*128+perm_idx[i]],label_id[perm_idx[i]].item()])
                elif(y_pred11[i].item()>=0.9 and y_pred22[i].item()>=0.9 and y_pred1[i].item()==y_pred2[i].item()):
                    if(y_pred1[i].item()==0):
                        label_0.append(0)
                        result4.append([global_step*128+perm_idx[i],0,data0[global_step*128+perm_idx[i]], label_id[perm_idx[i]].item()])
                    elif(y_pred1[i].item()==1):
                        label_1.append(1)
                        result4.append([global_step*128+perm_idx[i],1,data0[global_step*128+perm_idx[i]], label_id[perm_idx[i]].item()])
                
                else:
                    result4.append([global_step*128+perm_idx[i], -1,data0[global_step*128+perm_idx[i]],label_id[perm_idx[i]].item()])
               
             
                

             
                
            if(global_step==ls-1):

                result_label.clear()
                result3.clear()
  
                print("###result3[i] ###:", len(result3))
                a = min(len(label_0), len(label_1))
                la_0=0
                la_1=0
                la_2=0
                la_3=0
               
                
                random.shuffle(result4)
                
                
                for i in range(0, len(result4)):

                    if(result4[i][1] == 0 and la_0<a):
                        if(temp_check[result4[i][0]][0] == 0):
                            temp_check[result4[i][0]][0]=1
                            temp_check[result4[i][0]][1] = 0
                            la_0+=1
                            continue

           
                    elif(result4[i][1] == 1 and la_1<a):
                        if(temp_check[result4[i][0]][0] == 0):
                            temp_check[result4[i][0]][0]=1
                            temp_check[result4[i][0]][1] = 1
                            la_1+=1
                            continue
               

                
                result_label.clear()
                result3.clear()

                fw = open('./temp_data/temp_train_IMDB.tsv', 'a', encoding='utf-8', newline='')
                wr = csv.writer(fw, delimiter='\t')
                
                fww = open('./temp_data/temp_train_na_IMDB.tsv', 'w', encoding='utf-8', newline='')
                wrr = csv.writer(fww, delimiter='\t')
                



                for i in range(0, len(temp_check)):
                    if(temp_check[i][0] == 1):
                        result_label.append(str(temp_check[i][3]))
                        result3.append(str(temp_check[i][1]))
                        wr.writerow([str(temp_check[i][1]),str(temp_check[i][2])])
                    else:
                        wrr.writerow([str(temp_check[i][3]),str(temp_check[i][2])])




                
                fw.close()
                fww.close()
                data0.clear()
                temp_check.clear()
                with open('./temp_data/temp_train_na_IMDB.tsv', "r", encoding='utf-8') as f:
                    lines = csv.reader(f, delimiter='\t')

                    for i in lines:
                        a=''
                        lines2 = i[1].split(' ')
                        b=0
                        for j in range(0, len(lines2)):
                            a+=lines2[j]+' '
                            b+=1

                        data0.append(a)
                        temp_check.append([0,-1,a,i[0]])
                print("################;" , len(data0))
                f.close()  
                
                

                dataset_temp = TaskDataset('./temp_data/temp_train_IMDB.tsv', pipeline)
                data_iter_temp = DataLoader(dataset_temp, batch_size=cfg.batch_size, shuffle=True)
                
                
                dataset_temp_na = TaskDataset('./temp_data/temp_train_na_IMDB.tsv', pipeline)
                data_iter_temp_na = DataLoader(dataset_temp_na, batch_size=cfg.batch_size, shuffle=False)


            if(global_step!=ls-1):
                data_iter_temp = 1
                data_iter_temp_na = 1



            return label_id, logits, result_label,result3, data_iter_temp, data_iter_temp_na
        
        def evalute_Attn_LSTM_SSL(model, batch):
            
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch
            
            seq_lengths, perm_idx = seq_lengths.sort(0, descending=True)
            input_ids = input_ids[perm_idx]
            label_id = label_id[perm_idx]
            token1 = embedding(input_ids.long())
            
            
            logits,attention_score = model2(token1.to(device=get_device()),input_ids, segment_ids, input_mask,seq_lengths)

            return label_id, logits
        if(dataName == "IMDB"):
            labelNum = 2
            dataName= "IMDB"
            tdataName = "imdbtrain"
            testName = "IMDB_test"
            Dict2 = {
		    "0" : {},
		    "1" : {}
		    }
        elif(dataName == "AG"):
            labelNum = 4
            dataName = "AGNews"
            tdataName = "agtrain"
            testName = "ag_test"
            Dict2 = {
		    "0" : {},
		    "1" : {},
		    "2" : {},
		    "3" : {}
		    }
        elif(dataName == "yahoo"):
            labelNum = 10
            dataName = "yahoo"
            tdataName = "yahootrain"
            testName = "yahoo_test"
            Dict2 = {
		    "0" : {},
		    "1" : {},
		    "2" : {},
		    "3" : {},
		    "4" : {},
		    "5" : {},
		    "6" : {},
		    "7" : {},
		    "8" : {},
		    "9" : {}
		    }
        
        
        elif(dataName == "dbpedia"):
            labelNum = 14
            dataName == "dbpedia"
            tdataName = "dbtrain"
            testName = "db_test"
            Dict2 = {
		    "0" : {},
		    "1" : {},
		    "2" : {},
		    "3" : {},
		    "4" : {},
		    "5" : {},
		    "6" : {},
		    "7" : {},
		    "8" : {},
		    "9" : {},
		    "10" : {},
		    "11" : {},
		    "12" : {},
		    "13" : {}
		    }
      
        curNum=1

        for kkk in  range(0, 5):
            #kkk+=1
            print(dataName)
            print(stopNum)
            
            cfg = train.Config.from_json(train_cfg)


            tokenizer = tokenization.FullTokenizer(do_lower_case=True)


            print("max_lenmax_len#:", max_len)

            TaskDataset = dataset_class(task) # task dataset class according to the task
            pipeline = [Tokenizing(tokenizer.convert_to_unicode, tokenizer.tokenize),
                        AddSpecialTokensWithTruncation(max_len),
                        TokenIndexing(tokenizer.convert_tokens_to_ids,
                                      TaskDataset.labels, max_len)]




            data_unlabeled_file = "./data/"+dataName + "_unlabeled" + str(kkk+1)+".tsv"
            data_dev_file = "./data/" + dataName + "_dev" + str(kkk+1)+".tsv"
            data_labeled_file = "./data/" + dataName + "_labeled" + str(kkk+1)+".tsv"
            data_total_file = "./total_data/" + tdataName + ".tsv"
            data_test_file = "./total_data/" + testName + ".tsv"
            f_total = open(data_total_file, 'r', encoding='utf-8')
            r_total = csv.reader(f_total, delimiter='\t')

            allD=[]
            for line in r_total:
                allD.append([line[0],line[1]])
            f_total.close()

            for ii in range(0, kkk+1):
                random.shuffle(allD)
                
            num_data = len(allD)
            num_data_dev_temp = int(int(num_data*0.01)/labelNum)
            num_data_dev = int(int(num_data_dev_temp*0.15)/labelNum)
            num_data_labeled = int(int(num_data_dev_temp*0.85)/labelNum)
            num_data_unlabeled = num_data - int(num_data_dev_temp*labelNum)


#            num_data_dev_temp = 20 * labelNum
#            num_data_dev = 10 * labelNum
#            num_data_labeled = 10 * labelNum
#            #num_data_unlabeled = 200000 - num_data_dev_temp
#            num_data_unlabeled = len(allD) - num_data_dev_temp
            
            print("num_data_dev#: ", num_data_dev)
            print("num_data_labeled#: ",num_data_labeled)
            print("num_data_unlabeled#: ",num_data_unlabeled)


            f_temp = open('./data/temp_data.tsv', 'w', encoding='utf-8', newline='')
            w_temp = csv.writer(f_temp, delimiter='\t')

            f_unlabeled = open(data_unlabeled_file, 'w', encoding='utf-8', newline='')
            w_unlabeled = csv.writer(f_unlabeled, delimiter='\t')
           
            allD2=[]
            tempD={}
            for line in allD:
                if(line[0] not in tempD):
                    allD2.append([line[0],line[1]])
                    tempD[line[0]] = 1
                elif(tempD[line[0]] <= int(num_data_dev_temp/labelNum)):
                    allD2.append([line[0],line[1]])
                    tempD[line[0]] += 1
                elif(tempD[line[0]] <= int(num_data_dev_temp/labelNum)+int(num_data_unlabeled/labelNum)):
                    allD2.append([line[0],line[1]])
                    tempD[line[0]] += 1

            tempD={}
            for line in allD2:
                if(line[0] not in tempD):
                    tempD[line[0]] = 1
                    w_temp.writerow([line[0],line[1]])
                elif(tempD[line[0]] <= int(num_data_dev_temp/labelNum)):
                    tempD[line[0]] += 1
                    w_temp.writerow([line[0],line[1]])
                elif(tempD[line[0]] <= int(num_data_dev_temp/labelNum)+int(num_data_unlabeled/labelNum)):
                    w_unlabeled.writerow([line[0],line[1]])
                    tempD[line[0]] += 1

            f_temp.close()
            f_unlabeled.close()                


            f_temp = open('./data/temp_data.tsv', 'r', encoding='utf-8')
            r_temp = csv.reader(f_temp, delimiter='\t')

            f_dev = open(data_dev_file, 'w', encoding='utf-8', newline='')
            w_dev = csv.writer(f_dev, delimiter='\t')

            f_labeled = open(data_labeled_file, 'w', encoding='utf-8', newline='')
            w_labeled = csv.writer(f_labeled, delimiter='\t')

            tempD={}
            for line in r_temp:
                if(line[0] not in tempD):
                    tempD[line[0]] = 1
                    w_dev.writerow([line[0],line[1]])
                elif(tempD[line[0]] <= (num_data_dev/labelNum)):
                    tempD[line[0]] += 1
                    w_dev.writerow([line[0],line[1]])
                else:
                    w_labeled.writerow([line[0],line[1]])
                
            f_temp.close()
            f_dev.close()
            f_labeled.close()
            
            
            dataset = TaskDataset(data_unlabeled_file, pipeline)
            data_iter = DataLoader(dataset, batch_size=cfg.batch_size, shuffle=False)

            dataset2 = TaskDataset(data_test_file, pipeline)
            data_iter2 = DataLoader(dataset2, batch_size=cfg.batch_size, shuffle=False)


            dataset_dev = TaskDataset(data_dev_file, pipeline)
            data_iter_dev = DataLoader(dataset_dev, batch_size=cfg.batch_size, shuffle=False)


            dataset3 = TaskDataset(data_labeled_file, pipeline)
            data_iter3 = DataLoader(dataset3, batch_size=cfg.batch_size, shuffle=True)

            weights = tokenization.embed_lookup2()

            print("#train_set:", len(data_iter))
            print("#test_set:", len(data_iter2))
            print("#short_set:", len(data_iter3))
            print("#dev_set:", len(data_iter_dev))
            curNum+=1


            embedding = nn.Embedding.from_pretrained(weights).to(device=get_device())
            criterion = nn.CrossEntropyLoss()

            
            model1 = Classifier_CNN(labelNum)
            model2 = Classifier_Attention_LSTM(labelNum)

            trainer = train.Trainer(cfg,
                                    dataName,
                                    stopNum,
                                    model1,
                                    model2,
                                    data_iter,
                                    data_iter2,
                                     data_iter3,
                                     data_iter_dev,
                                     torch.optim.Adam(model1.parameters(), lr=0.001),
                                     torch.optim.Adam(model2.parameters(), lr=0.005),
                                     get_device(),kkk+1)



            label_0=[]
            label_1=[]

            result3=[]
            result4=[]


            bb_11={}
            bb_22={}


            abusive_11=[]
            abusive_22=[]

            result_label=[]

            fw = open('./temp_data/temp_train_IMDB.tsv', 'w', encoding='utf-8', newline='')
            wr = csv.writer(fw, delimiter='\t')

            fr = open(data_labeled_file, 'r', encoding='utf-8')
            rdrr = csv.reader(fr,  delimiter='\t')
            for line in rdrr:
                wr.writerow([line[0],line[1]])

            fw.close()
            fr.close()


            data0=[]
            temp_check=[]
            temp_label=[]

            with open(data_unlabeled_file, "r", encoding='utf-8') as f:
                lines = csv.reader(f, delimiter='\t')

                for i in lines:
                    a=''
                    lines2 = i[1].split(' ')
                    for j in range(0, len(lines2)):
                        a+=lines2[j]+' '


                    data0.append(a)
                    temp_check.append([0,-1,a,i[0]])
                    temp_label.append([0,0])
            f.close()   
          
            trainer.train(get_loss_CNN, get_loss_Attn_LSTM,evalute_CNN_SSL,pseudo_labeling,evalute_Attn_LSTM,evalute_CNN,evalute_Attn_LSTM_SSL,generating_lexiocn, data_parallel)



    elif mode == 'eval':
        def evalute_Attn_LSTM_SSL(model, batch):
            
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch
            
            seq_lengths, perm_idx = seq_lengths.sort(0, descending=True)
            input_ids = input_ids[perm_idx]
            label_id = label_id[perm_idx]
            token1 = embedding(input_ids.long())
            
            
            logits,attention_score = model2(token1.to(device=get_device()),input_ids, segment_ids, input_mask,seq_lengths)

            return label_id, logits
        
        def evalute_CNN_SSL(model, batch):
            input_ids, segment_ids, input_mask, label_id,seq_lengths = batch
            token1 = embedding(input_ids.long())
            logits,attention_score = model(token1.to(device=get_device()),input_ids, segment_ids, input_mask)

            return label_id, logits

        weights = tokenization.embed_lookup2()
        
        embedding = nn.Embedding.from_pretrained(weights).to(device=get_device())
        criterion = nn.CrossEntropyLoss()


        model = Classifier_CNN(2)
        model2 = Classifier_Attention_LSTM(2)

        trainer = train.Eval(cfg,
                                model,
                                model2,
                                data_iter,
                                save_dir, get_device())

        embedding = nn.Embedding.from_pretrained(weights).to(device=get_device())
        results = trainer.eval(evalute_CNN_SSL, evalute_Attn_LSTM_SSL, data_parallel)
        #total_accuracy = torch.cat(results).mean().item()
        #print('Accuracy:', total_accuracy)


if __name__ == '__main__':
    fire.Fire(main)
